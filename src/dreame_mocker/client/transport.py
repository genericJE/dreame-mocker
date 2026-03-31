"""HTTP transport layer — wraps httpx.AsyncClient with retries and header injection."""

from __future__ import annotations

import logging
from typing import Any, Self

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from dreame_mocker.const import CLIENT_CREDENTIALS_B64

from .crypto import make_dreame_rlc
from .errors import RateLimitError, TransportError
from .regions import base_url

logger = logging.getLogger(__name__)

# Retry on transient failures only.
_RETRYABLE = retry_if_exception_type((
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    TransportError,
))

_RETRY_POLICY = retry(
    retry=_RETRYABLE,
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)


class DreameTransport:
    """Async HTTP transport for the Dreame cloud API.

    Handles:
    - Header injection (auth, RLC, tenant, user-agent)
    - Retry with exponential backoff on transient failures
    - Region switching mid-session
    """

    def __init__(
        self,
        region: str,
        host: str | None = None,
        port: int = 13267,
        timeout: float = 15.0,
        *,
        is_mock: bool = False,
    ) -> None:
        self._region = region
        self._host = host
        self._port = port
        self._timeout = timeout
        self._is_mock = is_mock
        self._token: str | None = None
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.close()

    async def open(self) -> None:
        """Create the underlying httpx client."""
        self._client = self._make_client()

    async def close(self) -> None:
        """Close the underlying httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def region(self) -> str:
        return self._region

    def set_token(self, token: str) -> None:
        """Update the bearer token used in subsequent requests."""
        self._token = token

    async def switch_region(self, region: str) -> None:
        """Recreate the httpx client pointed at a new region."""
        if region == self._region:
            return
        logger.info("Switching transport from %s to %s", self._region, region)
        self._region = region
        if self._client:
            await self._client.aclose()
        self._client = self._make_client()

    @_RETRY_POLICY
    async def post(
        self,
        path: str,
        *,
        data: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Send a POST request with full header injection and retry."""
        client = self._ensure_client()
        headers = self._build_headers()
        if extra_headers:
            headers.update(extra_headers)

        logger.debug("POST %s", path)
        resp = await client.post(
            path, data=data, json=json, params=params, headers=headers,
        )

        # Handle rate limiting.
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            raise RateLimitError(
                f"Rate limited on {path}",
                retry_after=float(retry_after) if retry_after else None,
            )

        # Surface 5xx as TransportError so tenacity retries them.
        if resp.status_code >= 500:
            raise TransportError(
                f"Server error {resp.status_code} on {path}: {resp.text[:200]}"
            )

        return resp

    @retry(
        retry=_RETRYABLE,
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    async def download(self, url: str) -> bytes:
        """Download from an arbitrary URL (e.g. pre-signed map file URL)."""
        async with httpx.AsyncClient(timeout=30.0) as tmp:
            resp = await tmp.get(url)
            if resp.status_code >= 500:
                raise TransportError(f"Download error {resp.status_code}: {url}")
            resp.raise_for_status()
            return resp.content

    # --- Private ---

    def _make_client(self) -> httpx.AsyncClient:
        if self._is_mock:
            host = self._host or "localhost"
            url = f"http://{host}:{self._port}"
        else:
            url = base_url(self._region, self._port)
        return httpx.AsyncClient(base_url=url, timeout=self._timeout)

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            msg = "Transport not open. Use `async with` or call open() first."
            raise TransportError(msg)
        return self._client

    def _build_headers(self) -> dict[str, str]:
        if self._is_mock:
            if self._token:
                return {"Authorization": f"Bearer {self._token}"}
            return {}
        headers = {
            "Authorization": f"Basic {CLIENT_CREDENTIALS_B64}",
            "Tenant-Id": "000000",
            "Dreame-Meta": "cv=i_829",
            "Dreame-Rlc": make_dreame_rlc(self._region),
            "User-Agent": "Dreame_Smarthome/2.1.9 (iPhone; iOS 18.4.1; Scale/3.00)",
        }
        if self._token:
            headers["Dreame-Auth"] = f"bearer {self._token}"
        return headers
