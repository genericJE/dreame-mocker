"""FastAPI application — mocks the Dreamehome cloud API."""
# pyright: reportUnusedFunction=false

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .auth import TokenStore
from .const import AUTH_PATH, DEVICE_LIST_PATH, MAP_DOWNLOAD_URL_PATH, PROPERTIES_PATH, SEND_COMMAND_PATH
from .map_encoder import generate_mock_map
from .state import DeviceRegistry, VacuumDevice

logger = logging.getLogger("dreame_mocker")

# Default no-op lifespan
@asynccontextmanager
async def _default_lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    yield


def create_app(
    registry: DeviceRegistry,
    token_store: TokenStore,
    lifespan: Any = None,
) -> FastAPI:
    app = FastAPI(
        title="Dreame Mocker",
        version="0.1.0",
        lifespan=lifespan or _default_lifespan,
    )

    # --- helpers ---

    def _require_auth(authorization: str | None) -> None:
        if not authorization:
            raise HTTPException(401, "Missing authorization header")
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(401, "Invalid authorization header")
        if not token_store.validate(parts[1]):
            raise HTTPException(401, "Invalid or expired token")

    # --- OAuth2 token endpoint ---

    @app.post(AUTH_PATH)
    async def oauth_token(  # noqa: ARG001 (registered via decorator)
        grant_type: str = Form(...),
        username: str = Form(default=""),
        password: str = Form(default=""),
        refresh_token: str = Form(default=""),
    ) -> JSONResponse:
        if grant_type == "password":
            if not username:
                raise HTTPException(400, "username required")
            record = token_store.issue(username)
            logger.info("Issued token for %s", username)
            return JSONResponse(dict(record))

        if grant_type == "refresh_token":
            record = token_store.refresh(refresh_token)
            if not record:
                raise HTTPException(401, "Invalid refresh token")
            return JSONResponse(dict(record))

        raise HTTPException(400, f"Unsupported grant_type: {grant_type}")

    # --- Device list ---

    @app.post(DEVICE_LIST_PATH)
    async def device_list(  # noqa: ARG001
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_auth(authorization)
        devices = [d.to_device_info() for d in registry.all()]
        return JSONResponse({"code": 0, "msg": "ok", "data": devices})

    # --- Send command (RPC) ---

    @app.post(SEND_COMMAND_PATH)
    async def send_command(  # noqa: ARG001
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_auth(authorization)
        body: dict[str, Any] = await request.json()
        did: str = body.get("did", "")
        data: dict[str, Any] = body.get("data", {})
        method: str = data.get("method", "")
        params: Any = data.get("params", [])

        device = registry.get(did)
        if not device:
            raise HTTPException(404, f"Device {did} not found")

        result = await _handle_rpc(device, method, params)
        return JSONResponse({
            "code": 0,
            "data": {"id": data.get("id", 1), "result": result},
            "success": True,
        })

    # --- Batch property read/write ---

    @app.post(PROPERTIES_PATH)
    async def properties(  # noqa: ARG001
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_auth(authorization)
        body: dict[str, Any] = await request.json()
        did: str = body.get("did", "")
        device = registry.get(did)
        if not device:
            raise HTTPException(404, f"Device {did} not found")

        action: str = body.get("action", "get")
        specs: list[dict[str, Any]] = body.get("params", [])

        if action == "set":
            results = device.set_properties_batch(specs)
        else:
            results = device.get_properties_batch(specs)

        return JSONResponse({"code": 0, "data": results})

    # --- Map support ---

    _mock_map_data = generate_mock_map()

    @app.post(MAP_DOWNLOAD_URL_PATH)
    async def get_download_url(  # noqa: ARG001
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_auth(authorization)
        body: dict[str, Any] = await request.json()
        filename: str = body.get("filename", "mock/map/current.bin")
        host = request.headers.get("host", "localhost:13267")
        url = f"http://{host}/mock-map/{filename}"
        return JSONResponse({"code": 0, "data": {"url": url}})

    @app.get("/mock-map/{path:path}")
    async def serve_map(path: str) -> Response:  # noqa: ARG001
        return Response(content=_mock_map_data, media_type="application/octet-stream")

    return app


async def _handle_rpc(
    device: VacuumDevice,
    method: str,
    params: list[dict[str, Any]] | dict[str, Any],
) -> list[dict[str, Any]] | dict[str, Any]:
    if method == "get_properties" and isinstance(params, list):
        return device.get_properties_batch(params)

    if method == "set_properties" and isinstance(params, list):
        return device.set_properties_batch(params)

    if method == "action" and isinstance(params, dict):
        siid = int(params["siid"]) if "siid" in params else None
        aiid = int(params["aiid"]) if "aiid" in params else None
        action_in: list[Any] | None = params.get("in") if isinstance(params.get("in"), list) else None
        if siid is not None and aiid is not None:
            return await device.execute_action(siid, aiid, action_in)
        return {"code": -1, "message": "Missing siid/aiid"}

    # Fallback: try to interpret as action if siid/aiid present in params
    if isinstance(params, dict) and "siid" in params and "aiid" in params:
        fallback_in: list[Any] | None = params.get("in") if isinstance(params.get("in"), list) else None
        return await device.execute_action(
            int(params["siid"]), int(params["aiid"]), fallback_in,
        )

    return {"code": -1, "message": f"Unknown method: {method}"}
