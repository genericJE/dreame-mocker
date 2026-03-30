"""Pydantic models for API requests and responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


# --- Auth ---

class TokenResponse(BaseModel):
    _key: str = Field(alias="access_token")
    _secondary_key: str = Field(alias="refresh_token")
    _uuid: str = Field(alias="uid")
    _key_expire: int = Field(alias="expires_in")
    token_type: str = "bearer"


# --- Device list ---

class DeviceInfo(BaseModel):
    did: str
    name: str
    model: str
    mac: str
    token: str
    localip: str
    region: str
    firmware_version: str
    feature: int = 0
    property_: dict = Field(default_factory=dict, alias="property")


class DeviceListResponse(BaseModel):
    code: int = 0
    msg: str = "ok"
    data: list[DeviceInfo] = Field(default_factory=list)


# --- RPC command ---

class RPCParams(BaseModel):
    did: str
    id: int = 1
    method: str
    params: list | dict | None = None


class RPCRequest(BaseModel):
    did: str
    id: int = 1
    data: RPCParams


class RPCResult(BaseModel):
    code: int = 0
    data: dict = Field(default_factory=dict)
    success: bool = True


# --- Property get/set ---

class PropertySpec(BaseModel):
    siid: int
    piid: int
    did: str | None = None
    value: int | str | bool | None = None


# --- MQTT status message ---

class MQTTStatusMessage(BaseModel):
    did: str
    siid: int
    piid: int
    value: int | str | bool
