"""Exception hierarchy for the Dreame cloud client."""

from __future__ import annotations


class DreameError(Exception):
    """Base exception for all Dreame client errors."""


class AuthenticationError(DreameError):
    """Failed to authenticate with the Dreame cloud."""


class TokenExpiredError(AuthenticationError):
    """The access token has expired and could not be refreshed."""


class TokenRevokedError(AuthenticationError):
    """The token was revoked server-side."""


class RegionMismatchError(DreameError):
    """The configured region does not match the account's device region."""


class DeviceNotFoundError(DreameError):
    """The requested device was not found in the account."""


class DeviceOfflineError(DreameError):
    """The device is offline and cannot receive commands."""


class RateLimitError(DreameError):
    """The API rate limit has been exceeded."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TransportError(DreameError):
    """A transport-level error occurred (network, timeout, etc.)."""


class MapDecodeError(DreameError):
    """Failed to decode map data from the robot."""
