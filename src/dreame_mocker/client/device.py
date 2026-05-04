"""DreameDevice — typed abstraction over a single Dreame robot vacuum."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, cast

from dreame_mocker.const import (
    SEND_COMMAND_PATH,
    STATES,
    Action,
    Property,
)

from .auth import AuthManager
from .errors import AuthenticationError, DeviceOfflineError, DreameError
from .map_decoder import DreameMap, MapDecoder
from .transport import DreameTransport

logger = logging.getLogger(__name__)


def _extract_prop_list(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the property result list from an RPC response."""
    data: dict[str, Any] = result.get("data", result)
    prop_list: Any = data.get("result", data)
    if isinstance(prop_list, list):
        return cast(list[dict[str, Any]], prop_list)
    return []


@dataclass
class DeviceStatus:
    """Snapshot of commonly-read device properties."""

    state: int
    state_name: str
    battery: int
    error: int
    suction_level: int
    water_volume: int
    cleaning_mode: int
    cleaning_time: int
    cleaning_area: int


class DreameDevice:
    """High-level interface to a single Dreame robot vacuum.

    Every method auto-refreshes the auth token and retries once on 401.
    """

    def __init__(
        self,
        did: str,
        model: str,
        name: str,
        transport: DreameTransport,
        auth: AuthManager,
    ) -> None:
        self.did = did
        self.model = model
        self.name = name
        self._transport = transport
        self._auth = auth

    def __repr__(self) -> str:
        return f"DreameDevice({self.name!r}, did={self.did!r}, model={self.model!r})"

    # ── Property getters ──────────────────────────────────────────────

    async def get_state(self) -> int:
        """Current device state (see ``const.STATES`` for meanings)."""
        return int(await self._get_prop(Property.STATE))

    async def get_battery(self) -> int:
        """Battery level, 0-100."""
        return int(await self._get_prop(Property.BATTERY_LEVEL))

    async def get_error(self) -> int:
        """Error code (0 = no error)."""
        return int(await self._get_prop(Property.ERROR))

    async def get_suction_level(self) -> int:
        """Suction level (see ``const.SuctionLevel``)."""
        return int(await self._get_prop(Property.SUCTION_LEVEL))

    async def get_water_volume(self) -> int:
        """Water volume (see ``const.WaterVolume``)."""
        return int(await self._get_prop(Property.WATER_VOLUME))

    async def get_cleaning_mode(self) -> int:
        """Cleaning mode (see ``const.CleaningMode``)."""
        return int(await self._get_prop(Property.CLEANING_MODE))

    async def get_cleaning_time(self) -> int:
        """Elapsed cleaning time in seconds."""
        return int(await self._get_prop(Property.CLEANING_TIME))

    async def get_cleaning_area(self) -> int:
        """Cleaned area in m^2."""
        return int(await self._get_prop(Property.CLEANING_AREA))

    async def get_volume(self) -> int:
        """Speaker volume, 0-100."""
        return int(await self._get_prop(Property.VOLUME))

    async def get_dnd_enabled(self) -> bool:
        """Whether Do Not Disturb is enabled."""
        val = await self._get_prop(Property.DND_ENABLED)
        return bool(val)

    async def get_status(self) -> DeviceStatus:
        """Batch-read common properties in a single RPC call."""
        props = await self.get_properties([
            Property.STATE,
            Property.BATTERY_LEVEL,
            Property.ERROR,
            Property.SUCTION_LEVEL,
            Property.WATER_VOLUME,
            Property.CLEANING_MODE,
            Property.CLEANING_TIME,
            Property.CLEANING_AREA,
        ])
        values = [p.get("value", 0) for p in props]
        state = int(values[0])
        return DeviceStatus(
            state=state,
            state_name=STATES.get(state, str(state)),
            battery=int(values[1]),
            error=int(values[2]),
            suction_level=int(values[3]),
            water_volume=int(values[4]),
            cleaning_mode=int(values[5]),
            cleaning_time=int(values[6]),
            cleaning_area=int(values[7]),
        )

    # ── Property setters ──────────────────────────────────────────────

    async def set_suction_level(self, level: int) -> None:
        """Set suction level (see ``const.SuctionLevel``)."""
        await self._set_prop(Property.SUCTION_LEVEL, level)

    async def set_water_volume(self, volume: int) -> None:
        """Set water volume (see ``const.WaterVolume``)."""
        await self._set_prop(Property.WATER_VOLUME, volume)

    async def set_cleaning_mode(self, mode: int) -> None:
        """Set cleaning mode (see ``const.CleaningMode``)."""
        await self._set_prop(Property.CLEANING_MODE, mode)

    async def set_volume(self, volume: int) -> None:
        """Set speaker volume (0-100)."""
        await self._set_prop(Property.VOLUME, volume)

    async def set_dnd(
        self,
        enabled: bool,
        start_hour: int = 22,
        start_minute: int = 0,
        end_hour: int = 7,
        end_minute: int = 0,
    ) -> None:
        """Configure Do Not Disturb schedule."""
        await self.set_properties([
            (*Property.DND_ENABLED, enabled),
            (*Property.DND_START_HOUR, start_hour),
            (*Property.DND_START_MINUTE, start_minute),
            (*Property.DND_END_HOUR, end_hour),
            (*Property.DND_END_MINUTE, end_minute),
        ])

    # ── Actions ───────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start cleaning in the current cleaning mode."""
        await self.send_action(*Action.START)

    async def pause(self) -> None:
        """Pause the current cleaning cycle."""
        await self.send_action(*Action.PAUSE)

    async def stop(self) -> None:
        """Stop cleaning, go idle."""
        await self.send_action(*Action.STOP)

    async def return_to_dock(self) -> None:
        """Return to the charging dock."""
        await self.send_action(*Action.CHARGE)

    async def start_mop_wash(self) -> None:
        """Start a mop pad wash cycle."""
        await self.send_action(*Action.START_WASHING)

    async def start_mop_dry(self) -> None:
        """Start mop pad drying."""
        await self.send_action(*Action.START_DRYING)

    async def start_dust_collection(self) -> None:
        """Trigger dustbin auto-empty."""
        await self.send_action(*Action.START_AUTO_EMPTY)

    # ── Map ───────────────────────────────────────────────────────────

    async def get_map(self, req_type: int = 1) -> DreameMap:
        """Request, download, and decode a map.

        ``req_type`` selects the map variant: 1 = current, 2 = saved.
        """
        return await MapDecoder.request_and_decode(
            self._transport, self.did, self.model, req_type=req_type,
        )

    # ── Low-level RPC ─────────────────────────────────────────────────

    async def send_action(
        self,
        siid: int,
        aiid: int,
        params: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send an action command to the device."""
        action_params: dict[str, Any] = {
            "did": self.did,
            "siid": siid,
            "aiid": aiid,
        }
        if params:
            action_params["in"] = params

        return await self._rpc("action", action_params)

    async def get_properties(
        self, specs: list[tuple[int, int]],
    ) -> list[dict[str, Any]]:
        """Batch-read properties by (siid, piid) tuples."""
        params = [
            {"siid": siid, "piid": piid, "did": self.did}
            for siid, piid in specs
        ]
        result = await self._rpc("get_properties", params)
        return _extract_prop_list(result)

    async def set_properties(
        self, specs: list[tuple[int, int, Any]],
    ) -> list[dict[str, Any]]:
        """Batch-write properties by (siid, piid, value) tuples."""
        params = [
            {"siid": siid, "piid": piid, "did": self.did, "value": value}
            for siid, piid, value in specs
        ]
        result = await self._rpc("set_properties", params)
        return _extract_prop_list(result)

    # ── Private ───────────────────────────────────────────────────────

    async def _get_prop(self, prop: tuple[int, int]) -> Any:
        """Read a single property value."""
        results = await self.get_properties([prop])
        if results:
            return results[0].get("value", 0)
        return 0

    async def _set_prop(self, prop: tuple[int, int], value: Any) -> None:
        """Write a single property value."""
        await self.set_properties([(*prop, value)])

    async def _rpc(
        self, method: str, params: dict[str, Any] | list[Any],
    ) -> dict[str, Any]:
        """Send an RPC command with auto-refresh on 401."""
        await self._auth.ensure_valid_token()

        payload: dict[str, Any] = {
            "did": self.did,
            "id": 1,
            "data": {
                "did": self.did,
                "id": 1,
                "method": method,
                "params": params,
            },
        }

        resp = await self._transport.post(SEND_COMMAND_PATH, json=payload)

        # Retry once on 401.
        if resp.status_code == 401:
            logger.warning("Got 401 on %s, re-authenticating", method)
            try:
                await self._auth.revoke()
                await self._auth.authenticate()
            except AuthenticationError:
                raise
            resp = await self._transport.post(SEND_COMMAND_PATH, json=payload)
            if resp.status_code == 401:
                raise AuthenticationError("Re-auth failed, still getting 401")

        if resp.status_code != 200:
            raise DreameError(f"RPC {method} failed: HTTP {resp.status_code}")

        body: dict[str, Any] = resp.json()

        # Check for device-offline error codes.
        code = body.get("code", 0)
        if code == -1 or code == -9999:
            raise DeviceOfflineError(f"Device {self.did} is offline (code={code})")

        return body
