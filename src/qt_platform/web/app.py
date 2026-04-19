from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path


def build_option_power_app(runtime_service=None, replay_service=None):
    try:
        from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
        from fastapi.responses import FileResponse, JSONResponse
        from pydantic import BaseModel
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "FastAPI is required for serve-option-power. Install with: pip install -e .[web]"
        ) from exc

    static_dir = Path(__file__).resolve().parent / "static"
    app = FastAPI(title="Option Power Demo")

    @app.get("/")
    async def root():
        return FileResponse(static_dir / "research.html")

    @app.get("/legacy-option-power")
    async def legacy_option_power():
        return FileResponse(static_dir / "option_power.html")

    @app.get("/research")
    async def research():
        return FileResponse(static_dir / "research.html")

    @app.get("/option_power.css")
    async def css():
        return FileResponse(static_dir / "option_power.css")

    @app.get("/option_power.js")
    async def js():
        return FileResponse(static_dir / "option_power.js")

    @app.get("/research.css")
    async def research_css():
        return FileResponse(static_dir / "research.css")

    @app.get("/research.js")
    async def research_js():
        return FileResponse(static_dir / "research.js")

    @app.get("/api/option-power/snapshot")
    async def snapshot():
        if runtime_service is None and replay_service is None:
            raise HTTPException(status_code=404, detail="No option power service configured.")
        if runtime_service is None:
            return JSONResponse(replay_service.current_snapshot())
        return JSONResponse(runtime_service.current_snapshot())

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

    class ReplayRequest(BaseModel):
        start: str
        end: str

    @app.get("/api/option-power/replay/default")
    async def replay_default():
        if replay_service is None:
            raise HTTPException(status_code=404, detail="Replay service is not enabled.")
        metadata = replay_service.get_default_session_metadata()
        if metadata is None:
            raise HTTPException(status_code=404, detail="No default replay session is loaded.")
        return JSONResponse(metadata)

    @app.post("/api/option-power/replay/sessions")
    async def create_replay_session(payload: ReplayRequest):
        if replay_service is None:
            raise HTTPException(status_code=404, detail="Replay service is not enabled.")
        try:
            metadata = replay_service.create_session(
                start=datetime.fromisoformat(payload.start),
                end=datetime.fromisoformat(payload.end),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(metadata)

    @app.get("/api/option-power/replay/sessions/{session_id}")
    async def replay_session_metadata(session_id: str):
        if replay_service is None:
            raise HTTPException(status_code=404, detail="Replay service is not enabled.")
        metadata = replay_service.get_session_metadata(session_id)
        if metadata is None:
            raise HTTPException(status_code=404, detail="Replay session not found.")
        return JSONResponse(metadata)

    @app.get("/api/option-power/replay/sessions/{session_id}/snapshots/{index}")
    async def replay_snapshot(session_id: str, index: int):
        if replay_service is None:
            raise HTTPException(status_code=404, detail="Replay service is not enabled.")
        payload = replay_service.get_snapshot(session_id, index)
        if payload is None:
            raise HTTPException(status_code=404, detail="Replay snapshot not found.")
        return JSONResponse(payload)

    @app.get("/api/option-power/replay/sessions/{session_id}/bars")
    async def replay_bars(session_id: str):
        if replay_service is None:
            raise HTTPException(status_code=404, detail="Replay service is not enabled.")
        payload = replay_service.get_bars(session_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Replay session not found.")
        return JSONResponse(payload)

    @app.get("/api/option-power/replay/sessions/{session_id}/series")
    async def replay_series(session_id: str, names: str):
        if replay_service is None:
            raise HTTPException(status_code=404, detail="Replay service is not enabled.")
        requested_names = [name.strip() for name in names.split(",") if name.strip()]
        payload = replay_service.get_series(session_id, requested_names)
        if payload is None:
            raise HTTPException(status_code=404, detail="Replay session not found.")
        return JSONResponse(payload)

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
        return JSONResponse(payload)

    @app.get("/api/option-power/live/meta")
    async def live_meta():
        if runtime_service is None:
            raise HTTPException(status_code=404, detail="Live service is not enabled.")
        return JSONResponse(runtime_service.live_metadata())

    @app.get("/api/option-power/live/bars")
    async def live_bars():
        if runtime_service is None:
            raise HTTPException(status_code=404, detail="Live service is not enabled.")
        return JSONResponse(runtime_service.live_bars())

    @app.get("/api/option-power/live/series")
    async def live_series(names: str):
        if runtime_service is None:
            raise HTTPException(status_code=404, detail="Live service is not enabled.")
        requested_names = [name.strip() for name in names.split(",") if name.strip()]
        return JSONResponse(runtime_service.live_series(requested_names))

    @app.get("/api/option-power/live/snapshot/latest")
    async def live_snapshot_latest():
        if runtime_service is None:
            raise HTTPException(status_code=404, detail="Live service is not enabled.")
        return JSONResponse({"snapshot": runtime_service.current_snapshot()})

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
        return JSONResponse(payload)

    return app
