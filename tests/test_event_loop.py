"""The client must not do blocking TLS setup on the event loop.

Home Assistant flags ``SSLContext.load_verify_locations`` when it runs on
the loop, because reading the CA bundle is disk I/O. httpx does that for
every client it builds, so the transport has to build the context in a
worker thread and reuse it.
"""

from __future__ import annotations

import ssl
import threading
from typing import Any

import httpx
import pytest

from dreame_mocker.client.transport import DreameTransport


@pytest.fixture
def cert_load_threads(monkeypatch: pytest.MonkeyPatch) -> list[threading.Thread]:
    """Record the thread of every CA-bundle load."""
    threads: list[threading.Thread] = []
    original = ssl.SSLContext.load_verify_locations

    def recording(self: ssl.SSLContext, *args: Any, **kwargs: Any) -> None:
        threads.append(threading.current_thread())
        original(self, *args, **kwargs)

    monkeypatch.setattr(ssl.SSLContext, "load_verify_locations", recording)
    return threads


def _on_loop_thread(threads: list[threading.Thread]) -> list[threading.Thread]:
    return [t for t in threads if t is threading.current_thread()]


async def test_open_builds_tls_context_off_the_loop(
    cert_load_threads: list[threading.Thread],
) -> None:
    async with DreameTransport(region="eu"):
        pass
    assert cert_load_threads, "expected the CA bundle to be loaded"
    assert not _on_loop_thread(cert_load_threads)


async def test_mock_transport_builds_tls_context_off_the_loop(
    cert_load_threads: list[threading.Thread],
) -> None:
    # httpx builds a TLS context even for a plain-http base URL.
    async with DreameTransport(region="eu", host="127.0.0.1", is_mock=True):
        pass
    assert not _on_loop_thread(cert_load_threads)


async def test_tls_context_is_built_once_and_reused(
    cert_load_threads: list[threading.Thread], monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get(_self: httpx.AsyncClient, _url: str) -> httpx.Response:
        return httpx.Response(200, content=b"map", request=httpx.Request("GET", _url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    transport = DreameTransport(region="eu")
    await transport.open()
    loads_after_open = len(cert_load_threads)

    # Reconnect, region switch and download each build a new httpx client.
    await transport.close()
    await transport.open()
    await transport.switch_region("us")
    assert await transport.download("https://example.invalid/map") == b"map"
    await transport.close()

    assert len(cert_load_threads) == loads_after_open
    assert not _on_loop_thread(cert_load_threads)


async def test_download_before_open_builds_tls_context_off_the_loop(
    cert_load_threads: list[threading.Thread], monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get(_self: httpx.AsyncClient, _url: str) -> httpx.Response:
        return httpx.Response(200, content=b"map", request=httpx.Request("GET", _url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    assert await DreameTransport(region="eu").download("https://example.invalid/map") == b"map"
    assert cert_load_threads
    assert not _on_loop_thread(cert_load_threads)
