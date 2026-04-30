from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path


def build_option_power_app(runtime_service=None, replay_service=None):
    try:
        from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
        from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
        from fastapi.staticfiles import StaticFiles
        try:
            import orjson  # noqa: F401
            from fastapi.responses import ORJSONResponse as ApiJSONResponse
        except ImportError:  # pragma: no cover
            ApiJSONResponse = JSONResponse
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "FastAPI is required for serve-option-power. Install with: pip install -e .[web]"
        ) from exc

    frontend_dist_dir = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    frontend_index = frontend_dist_dir / "index.html"
    app = FastAPI(title="Option Power Demo")

    if (frontend_dist_dir / "assets").exists():
        app.mount("/assets", StaticFiles(directory=frontend_dist_dir / "assets"), name="frontend-assets")

    def _frontend_shell() -> HTMLResponse | FileResponse:
        if frontend_index.exists():
            return FileResponse(frontend_index)
        return HTMLResponse(
            """
<!doctype html>
<html lang="zh-Hant">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>qt-platform frontend</title>
    <style>
      body { font-family: sans-serif; margin: 3rem; background: #0f172a; color: #e2e8f0; }
      code { background: rgba(148, 163, 184, 0.18); padding: 0.2rem 0.4rem; border-radius: 0.35rem; }
      a { color: #7dd3fc; }
    </style>
  </head>
  <body>
    <h1>Frontend build not found.</h1>
    <p>Run <code>cd frontend && npm install && npm run dev</code> for local development.</p>
    <p>Run <code>cd frontend && npm run build</code> if you want FastAPI to serve the built SPA.</p>
  </body>
</html>
            """.strip()
        )

    @app.get("/")
    async def root():
        return _frontend_shell()

    @app.get("/research")
    async def research():
        return _frontend_shell()

    @app.get("/option-power")
    async def option_power():
        return _frontend_shell()

    @app.get("/portfolio")
    async def portfolio():
        return _frontend_shell()

    @app.get("/reports/{report_id}")
    async def report_detail(report_id: str):
        return _frontend_shell()

    @app.get("/api/option-power/snapshot")
    async def snapshot():
        if runtime_service is None and replay_service is None:
            raise HTTPException(status_code=404, detail="No option power service configured.")
        if runtime_service is None:
            return ApiJSONResponse(replay_service.current_snapshot())
        return ApiJSONResponse(runtime_service.current_snapshot())

    @app.websocket("/ws/option-power")
    async def option_power_ws(websocket: WebSocket):
        if runtime_service is None:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(runtime_service.current_snapshot())
                await asyncio.sleep(runtime_service.snapshot_interval_seconds)
        except WebSocketDisconnect:
            return

    @app.get("/api/option-power/replay/default")
    async def replay_default():
        if replay_service is None:
            raise HTTPException(status_code=404, detail="Replay service is not enabled.")
        metadata = replay_service.get_default_session_metadata()
        if metadata is None:
            raise HTTPException(status_code=404, detail="No default replay session is loaded.")
        return ApiJSONResponse(metadata)

    @app.post("/api/option-power/replay/sessions")
    async def create_replay_session(
        payload: dict | None = Body(None),
        start: str | None = Query(None),
        end: str | None = Query(None),
    ):
        if replay_service is None:
            raise HTTPException(status_code=404, detail="Replay service is not enabled.")
        payload_start = payload.get("start") if payload else None
        payload_end = payload.get("end") if payload else None
        resolved_start = payload_start or start
        resolved_end = payload_end or end
        if not resolved_start or not resolved_end:
            raise HTTPException(status_code=400, detail="Replay payload must include start and end.")
        try:
            metadata = replay_service.create_session(
                start=datetime.fromisoformat(resolved_start),
                end=datetime.fromisoformat(resolved_end),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return ApiJSONResponse(metadata)

    @app.get("/api/option-power/replay/sessions/{session_id}")
    async def replay_session_metadata(session_id: str):
        if replay_service is None:
            raise HTTPException(status_code=404, detail="Replay service is not enabled.")
        metadata = replay_service.get_session_metadata(session_id)
        if metadata is None:
            raise HTTPException(status_code=404, detail="Replay session not found.")
        return ApiJSONResponse(metadata)

    @app.get("/api/option-power/replay/sessions/{session_id}/progress")
    async def replay_progress(session_id: str):
        if replay_service is None:
            raise HTTPException(status_code=404, detail="Replay service is not enabled.")
        payload = replay_service.get_progress(session_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Replay session not found.")
        return ApiJSONResponse(payload)

    @app.get("/api/option-power/replay/sessions/{session_id}/events")
    async def replay_progress_events(session_id: str):
        if replay_service is None:
            raise HTTPException(status_code=404, detail="Replay service is not enabled.")
        if replay_service.get_progress(session_id) is None:
            raise HTTPException(status_code=404, detail="Replay session not found.")

        async def event_stream():
            last_ready_until: str | None = None
            while True:
                payload = replay_service.get_progress(session_id)
                if payload is None:
                    yield "event: error\ndata: {}\n\n"
                    return
                yield f"event: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                computed_until = payload.get("computed_until")
                if computed_until and computed_until != last_ready_until:
                    metadata = replay_service.get_session_metadata(session_id) or {}
                    range_payload = {
                        "session_id": session_id,
                        "start": metadata.get("start"),
                        "end": computed_until,
                        "computed_until": computed_until,
                        "compute_status": payload.get("compute_status"),
                    }
                    yield f"event: range_ready\ndata: {json.dumps(range_payload, ensure_ascii=False)}\n\n"
                    last_ready_until = computed_until
                if payload.get("compute_status") in {"ready", "failed"}:
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/api/option-power/replay/sessions/{session_id}/snapshots/{index}")
    async def replay_snapshot(session_id: str, index: int):
        if replay_service is None:
            raise HTTPException(status_code=404, detail="Replay service is not enabled.")
        payload = replay_service.get_snapshot(session_id, index)
        if payload is None:
            raise HTTPException(status_code=404, detail="Replay snapshot not found.")
        return ApiJSONResponse(payload)

    @app.get("/api/option-power/replay/sessions/{session_id}/bars")
    async def replay_bars(
        session_id: str,
        start: str | None = Query(None),
        end: str | None = Query(None),
        interval: str = Query("1m"),
        max_points: int | None = Query(None),
    ):
        if replay_service is None:
            raise HTTPException(status_code=404, detail="Replay service is not enabled.")
        try:
            resolved_start = datetime.fromisoformat(start) if start else None
            resolved_end = datetime.fromisoformat(end) if end else None
            _validate_replay_interval(interval)
            _validate_max_points(max_points)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload = replay_service.get_bars(
            session_id,
            start=resolved_start,
            end=resolved_end,
            interval=interval,
            max_points=max_points,
        )
        if payload is None:
            raise HTTPException(status_code=404, detail="Replay session not found.")
        return ApiJSONResponse(payload)

    @app.get("/api/option-power/replay/sessions/{session_id}/series")
    async def replay_series(
        session_id: str,
        names: str,
        start: str | None = Query(None),
        end: str | None = Query(None),
        interval: str = Query("1m"),
        max_points: int | None = Query(None),
        request_id: str | None = Query(None),
    ):
        if replay_service is None:
            raise HTTPException(status_code=404, detail="Replay service is not enabled.")
        requested_names = [name.strip() for name in names.split(",") if name.strip()]
        try:
            resolved_start = datetime.fromisoformat(start) if start else None
            resolved_end = datetime.fromisoformat(end) if end else None
            _validate_replay_interval(interval)
            _validate_max_points(max_points)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload = replay_service.get_series_payload(
            session_id,
            requested_names,
            start=resolved_start,
            end=resolved_end,
            interval=interval,
            max_points=max_points,
            request_id=request_id,
        )
        if payload is None:
            raise HTTPException(status_code=404, detail="Replay session not found.")
        return ApiJSONResponse(payload)

    @app.get("/api/option-power/replay/sessions/{session_id}/bundle")
    async def replay_bundle(
        session_id: str,
        names: str,
        start: str | None = Query(None),
        end: str | None = Query(None),
        interval: str = Query("1m"),
        max_points: int | None = Query(None),
        request_id: str | None = Query(None),
    ):
        if replay_service is None:
            raise HTTPException(status_code=404, detail="Replay service is not enabled.")
        requested_names = [name.strip() for name in names.split(",") if name.strip()]
        try:
            resolved_start = datetime.fromisoformat(start) if start else None
            resolved_end = datetime.fromisoformat(end) if end else None
            _validate_replay_interval(interval)
            _validate_max_points(max_points)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload = replay_service.get_bundle(
            session_id,
            requested_names,
            start=resolved_start,
            end=resolved_end,
            interval=interval,
            max_points=max_points,
            request_id=request_id,
        )
        if payload is None:
            raise HTTPException(status_code=404, detail="Replay session not found.")
        return ApiJSONResponse(payload)

    @app.get("/api/option-power/replay/sessions/{session_id}/bundle-by-bars")
    async def replay_bundle_by_bars(
        session_id: str,
        names: str,
        anchor: str,
        direction: str = Query("next"),
        bar_count: int = Query(300),
        interval: str = Query("1m"),
        max_points: int | None = Query(None),
        request_id: str | None = Query(None),
    ):
        if replay_service is None:
            raise HTTPException(status_code=404, detail="Replay service is not enabled.")
        requested_names = [name.strip() for name in names.split(",") if name.strip()]
        try:
            resolved_anchor = datetime.fromisoformat(anchor)
            _validate_replay_interval(interval)
            if direction not in {"prev", "next", "around"}:
                raise ValueError(f"Unsupported replay bar direction: {direction}")
            if bar_count <= 0:
                raise ValueError("Replay bar_count must be greater than 0.")
            _validate_max_points(max_points)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload = replay_service.get_bundle_by_bars(
            session_id,
            requested_names,
            anchor=resolved_anchor,
            direction=direction,
            bar_count=bar_count,
            interval=interval,
            max_points=max_points,
            request_id=request_id,
        )
        if payload is None:
            raise HTTPException(status_code=404, detail="Replay session not found.")
        return ApiJSONResponse(payload)

    @app.get("/api/option-power/replay/sessions/{session_id}/snapshot-at")
    async def replay_snapshot_at(session_id: str, ts: str):
        if replay_service is None:
            raise HTTPException(status_code=404, detail="Replay service is not enabled.")
        try:
            snapshot_ts = datetime.fromisoformat(ts)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid ts format.") from exc
        payload = replay_service.get_snapshot_at(session_id, snapshot_ts)
        if payload is None:
            raise HTTPException(status_code=404, detail="Replay snapshot not found.")
        return ApiJSONResponse(payload)

    @app.get("/api/option-power/live/meta")
    async def live_meta():
        if runtime_service is None:
            raise HTTPException(status_code=404, detail="Live service is not enabled.")
        return ApiJSONResponse(runtime_service.live_metadata())

    @app.get("/api/option-power/live/bars")
    async def live_bars():
        if runtime_service is None:
            raise HTTPException(status_code=404, detail="Live service is not enabled.")
        return ApiJSONResponse(runtime_service.live_bars())

    @app.get("/api/option-power/live/series")
    async def live_series(names: str):
        if runtime_service is None:
            raise HTTPException(status_code=404, detail="Live service is not enabled.")
        requested_names = [name.strip() for name in names.split(",") if name.strip()]
        return ApiJSONResponse(runtime_service.live_series(requested_names))

    @app.get("/api/option-power/live/snapshot/latest")
    async def live_snapshot_latest(
        since: str | None = Query(None),
        names: str | None = Query(None),
        compact: bool = Query(False),
        include_bar: bool = Query(True),
    ):
        if runtime_service is None:
            raise HTTPException(status_code=404, detail="Live service is not enabled.")
        if compact:
            try:
                resolved_since = datetime.fromisoformat(since) if since else None
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid since format.") from exc
            requested_names = [name.strip() for name in names.split(",") if name.strip()] if names else []
            return ApiJSONResponse(
                runtime_service.live_latest_update(
                    since=resolved_since,
                    names=requested_names,
                    include_bar=include_bar,
                )
            )
        return ApiJSONResponse({"snapshot": runtime_service.current_snapshot()})

    @app.get("/api/option-power/live/snapshot-at")
    async def live_snapshot_at(ts: str):
        if runtime_service is None:
            raise HTTPException(status_code=404, detail="Live service is not enabled.")
        try:
            snapshot_ts = datetime.fromisoformat(ts)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid ts format.") from exc
        payload = runtime_service.live_snapshot_at(snapshot_ts)
        if payload is None:
            raise HTTPException(status_code=404, detail="Live snapshot not found.")
        return ApiJSONResponse(payload)

    return app


def _validate_replay_interval(interval: str) -> None:
    if interval not in {"1m", "5m", "15m", "30m"}:
        raise ValueError("Replay interval must be one of: 1m, 5m, 15m, 30m.")


def _validate_max_points(max_points: int | None) -> None:
    if max_points is not None and max_points <= 0:
        raise ValueError("max_points must be greater than 0.")
