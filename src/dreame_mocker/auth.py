"""OAuth2 token endpoint mock."""

from __future__ import annotations

import time
import uuid


class TokenStore:
    """Issues and validates mock tokens."""

    def __init__(self) -> None:
        self._tokens: dict[str, dict] = {}

    def issue(self, username: str) -> dict:
        access_token = uuid.uuid4().hex
        refresh_token = uuid.uuid4().hex
        uid = uuid.uuid4().hex[:16]
        expires_in = 7200

        record = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "uid": uid,
            "expires_in": expires_in,
            "token_type": "bearer",
            "username": username,
            "issued_at": time.time(),
        }
        self._tokens[access_token] = record
        return record

    def validate(self, token: str) -> bool:
        record = self._tokens.get(token)
        if not record:
            return False
        return (time.time() - record["issued_at"]) < record["expires_in"]

    def refresh(self, refresh_token: str) -> dict | None:
        for record in self._tokens.values():
            if record["refresh_token"] == refresh_token:
                return self.issue(record["username"])
        return None
