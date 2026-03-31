"""Token persistence -- cache tokens to disk so we don't re-auth every run."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path.home() / ".config" / "dreame-mocker" / "tokens.json"

# Refresh if less than this many seconds remain on the token.
_REFRESH_MARGIN_S = 300  # 5 minutes


@dataclass
class StoredToken:
    """A persisted access/refresh token pair with metadata."""

    access_token: str
    refresh_token: str
    uid: str
    expires_at: float  # absolute Unix timestamp
    region: str
    country: str
    username: str

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at

    @property
    def needs_refresh(self) -> bool:
        return time.time() >= (self.expires_at - _REFRESH_MARGIN_S)


class TokenStore:
    """Read/write token data to a JSON file on disk.

    File permissions are set to ``0o600`` (owner-only) on creation.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _DEFAULT_PATH

    def load(self) -> StoredToken | None:
        """Load a cached token from disk, or ``None`` if absent/corrupt."""
        if not self._path.exists():
            return None
        try:
            raw: dict[str, Any] = json.loads(self._path.read_text())
            return StoredToken(
                access_token=str(raw["access_token"]),
                refresh_token=str(raw["refresh_token"]),
                uid=str(raw["uid"]),
                expires_at=float(raw["expires_at"]),
                region=str(raw["region"]),
                country=str(raw["country"]),
                username=str(raw["username"]),
            )
        except (KeyError, ValueError, json.JSONDecodeError, OSError) as exc:
            logger.debug("Failed to load cached token: %s", exc)
            return None

    def save(self, token: StoredToken) -> None:
        """Persist a token to disk with restricted permissions."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(asdict(token), indent=2))
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass  # Windows doesn't support Unix permissions
        logger.debug("Token cached to %s", self._path)

    def clear(self) -> None:
        """Remove the cached token file."""
        try:
            self._path.unlink(missing_ok=True)
            logger.debug("Cleared cached token at %s", self._path)
        except OSError:
            pass
