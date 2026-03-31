"""Authentication manager — login flows, token refresh, auto-refresh before expiry."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from dreame_mocker.const import AUTH_PATH, EMAIL_CODE_PATH

from .crypto import hash_password, make_request_sign
from .errors import AuthenticationError, TokenExpiredError, TokenRevokedError
from .tokens import StoredToken, TokenStore
from .transport import DreameTransport

logger = logging.getLogger(__name__)


class AuthManager:
    """Handles all auth flows and keeps the token fresh.

    Lifecycle:
    1. ``authenticate()`` — full login (cached token -> refresh -> password)
    2. ``ensure_valid_token()`` — called before every API request; auto-refreshes
    """

    def __init__(
        self,
        transport: DreameTransport,
        token_store: TokenStore,
        username: str,
        password: str | None = None,
    ) -> None:
        self._transport = transport
        self._store = token_store
        self._username = username
        self._password = password
        self._token: StoredToken | None = None
        self._refresh_lock = asyncio.Lock()

    @property
    def token(self) -> StoredToken | None:
        return self._token

    async def authenticate(self) -> StoredToken:
        """Full auth flow with fallback chain.

        1. Load cached token from disk
        2. If valid and not near-expiry, use it
        3. If near-expiry, try refresh_token grant
        4. If no cached token or refresh fails, do full password login
        5. Persist new token to disk
        """
        # Try cached token.
        cached = self._store.load()
        if cached and cached.username == self._username:
            if not cached.needs_refresh:
                logger.info("Using cached token (uid=%s, expires in %.0fs)",
                            cached.uid, cached.expires_at - time.time())
                self._token = cached
                self._transport.set_token(cached.access_token)
                return cached

            # Try to refresh.
            try:
                refreshed = await self._refresh(cached.refresh_token)
                logger.info("Refreshed token (uid=%s)", refreshed.uid)
                return refreshed
            except AuthenticationError:
                logger.info("Token refresh failed, falling back to full login")

        # Full login.
        return await self.login_password()

    async def ensure_valid_token(self) -> str:
        """Return a valid access token, refreshing if necessary.

        Thread-safe: concurrent callers share one refresh operation.
        """
        async with self._refresh_lock:
            if self._token and not self._token.needs_refresh:
                return self._token.access_token

            if self._token and self._token.refresh_token:
                try:
                    refreshed = await self._refresh(self._token.refresh_token)
                    return refreshed.access_token
                except AuthenticationError:
                    logger.warning("Refresh failed, re-authenticating")

            token = await self.login_password()
            return token.access_token

    async def login_password(self) -> StoredToken:
        """Password login with MD5-hashed password."""
        if not self._password:
            raise AuthenticationError("No password configured")

        logger.info("Logging in as %s (password)", self._username)
        hashed = hash_password(self._password)
        resp = await self._transport.post(
            AUTH_PATH,
            data={
                "grant_type": "password",
                "scope": "all",
                "platform": "IOS",
                "type": "account",
                "username": self._username,
                "password": hashed,
                "country": "GB",
                "lang": "en",
            },
        )

        if resp.status_code == 401:
            body: dict[str, Any] = resp.json()
            raise AuthenticationError(f"Login failed: {body.get('msg', resp.text)}")

        if resp.status_code != 200:
            raise AuthenticationError(f"Login failed: HTTP {resp.status_code}")

        return self._process_token_response(resp.json())

    async def login_email_code(
        self,
        code: str | None = None,
        code_callback: Callable[[], Awaitable[str]] | None = None,
    ) -> StoredToken:
        """Email code login flow.

        If *code* is ``None``, calls *code_callback* to obtain it interactively.
        """
        code_key = await self._request_email_code()

        if code is None:
            if code_callback is None:
                raise AuthenticationError("No code or callback provided")
            code = await code_callback()

        resp = await self._transport.post(
            AUTH_PATH,
            params={
                "grant_type": "email",
                "email": self._username,
                "country": "GB",
                "lang": "en",
            },
            extra_headers={"Sms-Key": code_key, "Sms-Code": code},
        )

        if resp.status_code != 200:
            raise AuthenticationError(f"Email code auth failed: {resp.text}")

        return self._process_token_response(resp.json())

    async def revoke(self) -> None:
        """Clear the current token from memory and disk."""
        self._token = None
        self._store.clear()
        logger.info("Token revoked / cleared")

    # --- Private helpers ---

    async def _refresh(self, refresh_token: str) -> StoredToken:
        """Use refresh_token grant to obtain a new access token."""
        resp = await self._transport.post(
            AUTH_PATH,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )

        if resp.status_code == 401:
            raise TokenRevokedError("Refresh token rejected")

        if resp.status_code != 200:
            raise TokenExpiredError(f"Token refresh failed: HTTP {resp.status_code}")

        return self._process_token_response(resp.json())

    async def _request_email_code(self) -> str:
        """POST /dreame-auth/oauth/email — request a verification code."""
        timestamp_ms = str(int(time.time()) * 1000)
        sign_params = {"email": self._username, "lang": "en"}
        sign = make_request_sign(sign_params, timestamp_ms)

        resp = await self._transport.post(
            EMAIL_CODE_PATH,
            json={
                "email": self._username,
                "lang": "en",
                "sign": sign,
                "timestamp": timestamp_ms,
            },
        )

        body: dict[str, Any] = resp.json()
        if not body.get("success"):
            raise AuthenticationError(f"Failed to send email code: {body}")

        data: dict[str, Any] = body.get("data", {})
        code_key = str(data.get("codeKey", ""))
        if not code_key:
            raise AuthenticationError(f"No codeKey in response: {body}")

        remains = int(data.get("remains", 0))
        logger.info("Email code sent to %s (%d sends remaining)", self._username, remains)
        return code_key

    def _process_token_response(self, body: dict[str, Any]) -> StoredToken:
        """Parse a token response, persist it, and update transport."""
        access_token = str(body.get("access_token", ""))
        if not access_token:
            raise AuthenticationError(f"No access_token in response: {body}")

        expires_in = int(body.get("expires_in", 7200))
        token = StoredToken(
            access_token=access_token,
            refresh_token=str(body.get("refresh_token", "")),
            uid=str(body.get("uid", "")),
            expires_at=time.time() + expires_in,
            region=str(body.get("region", self._transport.region)),
            country=str(body.get("country", "")),
            username=self._username,
        )

        self._token = token
        self._transport.set_token(access_token)
        self._store.save(token)
        return token
