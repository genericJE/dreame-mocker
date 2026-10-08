"""Token persistence: async wrappers, and injecting a custom store."""

from __future__ import annotations

from pathlib import Path

from dreame_mocker.client import DreameCloud
from dreame_mocker.client.tokens import StoredToken, TokenStore

from .conftest import InMemoryTokenStore, MockCloud


async def test_default_store_async_roundtrip(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "tokens.json")
    assert await store.async_load() is None

    token = StoredToken(
        access_token="a", refresh_token="r", uid="u", expires_at=2e9,
        region="eu", country="EU", username="tester",
    )
    await store.async_save(token)
    assert await store.async_load() == token
    assert (tmp_path / "tokens.json").stat().st_mode & 0o777 == 0o600

    await store.async_clear()
    assert await store.async_load() is None


async def test_cloud_uses_injected_store(mock_cloud: MockCloud) -> None:
    store = InMemoryTokenStore()
    async with DreameCloud(
        username="tester", password="pw", host="127.0.0.1", token_store=store,
    ) as cloud:
        await cloud.connect()
    assert store.saves == 1
    assert store.token is not None
    assert mock_cloud.tokens.validate(store.token.access_token)
