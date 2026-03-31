"""DreameCloud — main entry point for the Dreame cloud client library."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Self, cast

from dreame_mocker.const import DEVICE_LIST_PATH

from .auth import AuthManager
from .device import DreameDevice
from .errors import DeviceNotFoundError
from .regions import region_for_country, region_from_host
from .tokens import TokenStore
from .transport import DreameTransport

logger = logging.getLogger(__name__)


def _extract_device_records(raw_data: Any) -> list[dict[str, Any]]:
    """Parse device list from either ``[...]`` or ``{"page": {"records": [...]}}``."""
    if isinstance(raw_data, dict):
        data = cast(dict[str, Any], raw_data)
        page = data.get("page")
        if isinstance(page, dict):
            page_d = cast(dict[str, Any], page)
            recs = page_d.get("records")
            if isinstance(recs, list):
                return cast(list[dict[str, Any]], recs)
        return []
    if isinstance(raw_data, list):
        return cast(list[dict[str, Any]], raw_data)
    return []


class DreameCloud:
    """Async client for the Dreame cloud API.

    Usage::

        async with DreameCloud(username="...", password="...") as cloud:
            await cloud.connect()
            device = await cloud.get_device()
            status = await device.get_status()
    """

    def __init__(
        self,
        username: str,
        password: str | None = None,
        region: str = "eu",
        host: str | None = None,
        port: int = 13267,
        token_path: Path | None = None,
    ) -> None:
        is_mock = host is not None
        resolved_region = region

        self._username = username
        self._port = port
        self._transport = DreameTransport(
            region=resolved_region, host=host, port=port, is_mock=is_mock,
        )
        self._token_store = TokenStore(path=token_path)
        self._auth = AuthManager(
            transport=self._transport,
            token_store=self._token_store,
            username=username,
            password=password,
        )
        self._uid: str = ""
        self._device_region: str = resolved_region
        self._connected = False

    async def __aenter__(self) -> Self:
        await self._transport.open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.disconnect()

    @property
    def region(self) -> str:
        """The resolved device region (may differ from auth region)."""
        return self._device_region

    @property
    def uid(self) -> str:
        return self._uid

    async def connect(self) -> None:
        """Authenticate and resolve the correct device region.

        1. Open transport if not already open
        2. Authenticate on configured region
        3. Read account country from token response
        4. If country maps to a different region, switch transport
        """
        if self._transport._client is None:
            await self._transport.open()
        token = await self._auth.authenticate()
        self._uid = token.uid

        # Resolve device region from account country.
        device_region = region_for_country(
            token.country, fallback=self._transport.region,
        )
        if device_region != self._transport.region:
            logger.info(
                "Account country is %s — switching to %s.iot.dreame.tech",
                token.country, device_region,
            )
            await self._transport.switch_region(device_region)
        self._device_region = device_region
        self._connected = True

        logger.info("Connected (uid=%s, region=%s)", self._uid, self._device_region)

    async def get_devices(self) -> list[dict[str, Any]]:
        """Fetch all devices bound to the account.

        Returns the raw device dicts from the API.
        """
        await self._auth.ensure_valid_token()
        resp = await self._transport.post(DEVICE_LIST_PATH)

        body: dict[str, Any] = resp.json()
        raw_data: Any = body.get("data", body.get("result", []))

        records = _extract_device_records(raw_data)

        logger.info("Found %d device(s)", len(records))
        return records

    async def get_device(self, did: str | None = None) -> DreameDevice:
        """Get a ``DreameDevice`` wrapper for a specific device.

        If *did* is ``None``, returns the first device on the account
        (convenience for single-device accounts).
        """
        devices = await self.get_devices()

        if not devices:
            raise DeviceNotFoundError("No devices found on this account")

        if did is None:
            dev = devices[0]
        else:
            dev = next((d for d in devices if d.get("did") == did), None)
            if dev is None:
                available = [str(d.get("did", "?")) for d in devices]
                raise DeviceNotFoundError(
                    f"Device {did} not found. Available: {available}"
                )

        device_did = str(dev.get("did", ""))
        device_model = str(dev.get("model", ""))
        device_name = str(
            dev.get("customName", dev.get("name", dev.get("model", "Unknown")))
        )

        logger.info("Using device: %s (did=%s, model=%s)", device_name, device_did, device_model)
        return DreameDevice(
            did=device_did,
            model=device_model,
            name=device_name,
            transport=self._transport,
            auth=self._auth,
        )

    async def disconnect(self) -> None:
        """Close the transport connection."""
        await self._transport.close()
        self._connected = False
