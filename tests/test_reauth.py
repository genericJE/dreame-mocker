"""A token the server no longer accepts must trigger one fresh login, not a failed request."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from dreame_mocker.client import DreameCloud, TokenRejectedError
from dreame_mocker.client.auth import AuthManager
from dreame_mocker.client.transport import DreameTransport
from dreame_mocker.const import AUTH_PATH

from .conftest import DEVICE_ID, InMemoryTokenStore, MockCloud, install_handler



def _cloud(store: InMemoryTokenStore) -> DreameCloud:
    return DreameCloud(username="tester", password="pw", host="127.0.0.1", token_store=store)


async def test_stale_cached_token_recovers_on_device_list(mock_cloud: MockCloud) -> None:
    store = InMemoryTokenStore()
    async with _cloud(store) as cloud:
        await cloud.connect()
        await cloud.get_device()
    first = store.token
    assert first is not None

    # The server forgets every token; the client's cached one still looks valid.
    mock_cloud.tokens.clear()
    async with _cloud(store) as cloud:
        await cloud.connect()  # reuses the cached token without asking the server
        device = await cloud.get_device()  # 401 -> fresh login -> retried

    assert device.did == DEVICE_ID
    assert store.token is not None
    assert store.token.access_token != first.access_token
    assert mock_cloud.tokens.validate(store.token.access_token)
    assert store.clears == 1


async def test_stale_token_recovers_mid_session_on_rpc(mock_cloud: MockCloud) -> None:
    store = InMemoryTokenStore()
    async with _cloud(store) as cloud:
        await cloud.connect()
        device = await cloud.get_device()
        mock_cloud.tokens.clear()
        status = await device.get_status()  # RPC gets 401, recovers transparently
    assert status.battery > 0
    assert store.token is not None
    assert mock_cloud.tokens.validate(store.token.access_token)


async def test_concurrent_401s_log_in_once(monkeypatch: pytest.MonkeyPatch) -> None:
    logins = 0
    token_json = {
        "access_token": "new", "refresh_token": "r", "uid": "u1",
        "expires_in": 7200, "region": "eu", "country": "EU",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal logins
        if request.url.path == AUTH_PATH:
            logins += 1
            return httpx.Response(200, json=token_json)
        if request.headers.get("Authorization") == "Bearer new":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(401, json={"msg": "nope"})

    install_handler(monkeypatch, httpx.MockTransport(handler))
    transport = DreameTransport(region="eu", host="127.0.0.1", is_mock=True)
    AuthManager(transport, token_store=InMemoryTokenStore(), username="u", password="p")
    transport.set_token("stale")

    async with transport:
        responses = await asyncio.gather(transport.post("/x"), transport.post("/x"))

    assert [r.status_code for r in responses] == [200, 200]
    assert logins == 1


async def test_persistent_401_raises_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    posts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        if request.url.path == AUTH_PATH:
            return httpx.Response(200, json={"access_token": "new", "expires_in": 7200})
        posts += 1
        return httpx.Response(401, json={"msg": "nope"})

    install_handler(monkeypatch, httpx.MockTransport(handler))
    transport = DreameTransport(region="eu", host="127.0.0.1", is_mock=True)
    AuthManager(transport, token_store=InMemoryTokenStore(), username="u", password="p")
    transport.set_token("stale")

    async with transport:
        with pytest.raises(TokenRejectedError):
            await transport.post("/x")
    assert posts == 2  # original + exactly one retry


async def test_401_without_token_or_handler_is_returned_as_is(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"msg": "nope"})

    install_handler(monkeypatch, httpx.MockTransport(handler))
    transport = DreameTransport(region="eu", host="127.0.0.1", is_mock=True)
    calls: list[str] = []

    async def reauth(rejected: str) -> str | None:
        calls.append(rejected)
        return None

    transport.set_unauthorized_handler(reauth)
    async with transport:
        assert (await transport.post("/x")).status_code == 401  # no token: handler skipped
        transport.set_token("t")
        assert (await transport.post("/x", allow_reauth=False)).status_code == 401
        assert (await transport.post("/x")).status_code == 401  # handler gave up -> original response
    assert calls == ["t"]
