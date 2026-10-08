"""Shared fixtures: an in-process mock cloud reached through httpx's ASGI transport."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from dreame_mocker.auth import TokenStore as ServerTokenStore
from dreame_mocker.client.tokens import StoredToken, TokenStore
from dreame_mocker.client.transport import DreameTransport
from dreame_mocker.server import create_app
from dreame_mocker.state import DeviceRegistry, VacuumDevice

DEVICE_ID = "1234567890"


@dataclass
class MockCloud:
    """The in-process mock server. ``tokens.clear()`` mimics a server restart."""

    app: FastAPI
    tokens: ServerTokenStore
    registry: DeviceRegistry


class InMemoryTokenStore(TokenStore):
    """Client-side token store that never touches disk."""

    def __init__(self) -> None:
        super().__init__(path=Path("/dev/null/unused"))
        self.token: StoredToken | None = None
        self.saves = 0
        self.clears = 0

    def load(self) -> StoredToken | None:
        return self.token

    def save(self, token: StoredToken) -> None:
        self.token = token
        self.saves += 1

    def clear(self) -> None:
        self.token = None
        self.clears += 1


@pytest.fixture
def mock_cloud(monkeypatch: pytest.MonkeyPatch) -> MockCloud:
    """Route every ``DreameTransport`` at a fresh mock server, no TCP involved."""
    registry = DeviceRegistry()
    registry.add(VacuumDevice(did=DEVICE_ID))
    tokens = ServerTokenStore()
    cloud = MockCloud(app=create_app(registry, tokens), tokens=tokens, registry=registry)

    def _make_client(_self: DreameTransport) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=cloud.app), base_url="http://mock",
        )

    monkeypatch.setattr(DreameTransport, "_make_client", _make_client)
    return cloud


def install_handler(
    monkeypatch: pytest.MonkeyPatch,
    handler: httpx.MockTransport | None = None,
) -> None:
    """Route ``DreameTransport`` at an ``httpx.MockTransport`` for unit tests."""
    assert handler is not None

    def _make_client(_self: DreameTransport) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=handler, base_url="http://mock")

    monkeypatch.setattr(DreameTransport, "_make_client", _make_client)
