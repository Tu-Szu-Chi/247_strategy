from __future__ import annotations

import asyncio
from pathlib import Path


def build_option_power_app(runtime_service):
    try:
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect
        from fastapi.responses import FileResponse, JSONResponse
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "FastAPI is required for serve-option-power. Install with: pip install -e .[web]"
        ) from exc

    static_dir = Path(__file__).resolve().parent / "static"
    app = FastAPI(title="Option Power Demo")

    @app.get("/")
    async def root():
        return FileResponse(static_dir / "option_power.html")

    @app.get("/option_power.css")
    async def css():
        return FileResponse(static_dir / "option_power.css")

    @app.get("/option_power.js")
    async def js():
        return FileResponse(static_dir / "option_power.js")

    @app.get("/api/option-power/snapshot")
    async def snapshot():
        return JSONResponse(runtime_service.current_snapshot())

    @app.websocket("/ws/option-power")
    async def option_power_ws(websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(runtime_service.current_snapshot())
                await asyncio.sleep(runtime_service.snapshot_interval_seconds)
        except WebSocketDisconnect:
            return

    return app
