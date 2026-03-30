"""FastAPI application — mocks the Dreamehome cloud API."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .auth import TokenStore
from .const import AUTH_PATH, DEVICE_LIST_PATH, PROPERTIES_PATH, SEND_COMMAND_PATH
from .state import DeviceRegistry

logger = logging.getLogger("dreame_mocker")


def create_app(
    registry: DeviceRegistry,
    token_store: TokenStore,
) -> FastAPI:
    app = FastAPI(title="Dreame Mocker", version="0.1.0")

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
    async def oauth_token(
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
            return JSONResponse(record)

        if grant_type == "refresh_token":
            record = token_store.refresh(refresh_token)
            if not record:
                raise HTTPException(401, "Invalid refresh token")
            return JSONResponse(record)

        raise HTTPException(400, f"Unsupported grant_type: {grant_type}")

    # --- Device list ---

    @app.post(DEVICE_LIST_PATH)
    async def device_list(authorization: str | None = Header(default=None)) -> JSONResponse:
        _require_auth(authorization)
        devices = [d.to_device_info() for d in registry.all()]
        return JSONResponse({"code": 0, "msg": "ok", "data": devices})

    # --- Send command (RPC) ---

    @app.post(SEND_COMMAND_PATH)
    async def send_command(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_auth(authorization)
        body = await request.json()
        did = body.get("did", "")
        data = body.get("data", {})
        method = data.get("method", "")
        params = data.get("params", [])

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
    async def properties(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        _require_auth(authorization)
        body = await request.json()
        did = body.get("did", "")
        device = registry.get(did)
        if not device:
            raise HTTPException(404, f"Device {did} not found")

        action = body.get("action", "get")
        specs = body.get("params", [])

        if action == "set":
            results = device.set_properties_batch(specs)
        else:
            results = device.get_properties_batch(specs)

        return JSONResponse({"code": 0, "data": results})

    return app


async def _handle_rpc(device, method: str, params: Any) -> Any:
    if method == "get_properties":
        return device.get_properties_batch(params)

    if method == "set_properties":
        return device.set_properties_batch(params)

    if method == "action":
        siid = params.get("siid") if isinstance(params, dict) else None
        aiid = params.get("aiid") if isinstance(params, dict) else None
        action_params = params.get("in") if isinstance(params, dict) else None
        if siid is not None and aiid is not None:
            return await device.execute_action(siid, aiid, action_params)
        return {"code": -1, "message": "Missing siid/aiid"}

    # Fallback: try to interpret as action if siid/aiid present in params
    if isinstance(params, dict) and "siid" in params and "aiid" in params:
        return await device.execute_action(
            params["siid"], params["aiid"], params.get("in"),
        )

    return {"code": -1, "message": f"Unknown method: {method}"}
