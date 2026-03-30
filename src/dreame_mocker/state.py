"""Device state machine — maintains virtual device state and handles transitions."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from .const import (
    Action,
    CleaningMode,
    DEFAULT_MODEL,
    DeviceState,
    Property,
    SuctionLevel,
    WaterVolume,
)


class VacuumDevice:
    """Simulated Dreame X50 Ultra Complete."""

    def __init__(
        self,
        did: str | None = None,
        name: str = "X50 Ultra Complete",
        model: str = DEFAULT_MODEL,
    ) -> None:
        self.did = did or str(uuid.uuid4().int)[:10]
        self.name = name
        self.model = model
        self.mac = "AA:BB:CC:DD:EE:FF"
        self.token = uuid.uuid4().hex
        self.localip = "192.168.1.100"
        self.region = "eu"
        self.firmware_version = "4.5.2_1132"

        self._on_property_change: list = []

        # Property store keyed by (siid, piid)
        self._properties: dict[tuple[int, int], Any] = {
            Property.STATE: DeviceState.CHARGING,
            Property.ERROR: 0,
            Property.BATTERY_LEVEL: 100,
            Property.CHARGING_STATUS: True,
            Property.SUCTION_LEVEL: SuctionLevel.STANDARD,
            Property.WATER_VOLUME: WaterVolume.MEDIUM,
            Property.CLEANING_MODE: CleaningMode.SWEEP_AND_MOP,
            Property.SELF_WASH_BASE_STATUS: 0,
            Property.CLEANING_TIME: 0,
            Property.CLEANING_AREA: 0,
            Property.DUST_COLLECTION: True,
            Property.AUTO_EMPTY_STATUS: 0,
            Property.MAIN_BRUSH_TIME_LEFT: 18000,
            Property.MAIN_BRUSH_LIFE_LEVEL: 100,
            Property.SIDE_BRUSH_TIME_LEFT: 10800,
            Property.SIDE_BRUSH_LIFE_LEVEL: 100,
            Property.FILTER_TIME_LEFT: 9000,
            Property.FILTER_LIFE_LEVEL: 100,
            Property.MOP_PAD_TIME_LEFT: 7200,
            Property.MOP_PAD_LIFE_LEVEL: 100,
            Property.DND_ENABLED: False,
            Property.DND_START_HOUR: 22,
            Property.DND_START_MINUTE: 0,
            Property.DND_END_HOUR: 7,
            Property.DND_END_MINUTE: 0,
            Property.VOLUME: 50,
            Property.TIMEZONE: "Europe/London",
        }

        self._cleaning_task: asyncio.Task | None = None
        self._cleaning_start: float | None = None

    def on_property_change(self, callback):
        self._on_property_change.append(callback)

    def _notify(self, key: tuple[int, int], value: Any) -> None:
        for cb in self._on_property_change:
            cb(self.did, key[0], key[1], value)

    def get_property(self, siid: int, piid: int) -> Any:
        return self._properties.get((siid, piid))

    def set_property(self, siid: int, piid: int, value: Any) -> bool:
        key = (siid, piid)
        if key not in self._properties:
            return False
        self._properties[key] = value
        self._notify(key, value)
        return True

    def get_properties_batch(
        self, specs: list[dict],
    ) -> list[dict]:
        results = []
        for spec in specs:
            siid, piid = spec["siid"], spec["piid"]
            value = self.get_property(siid, piid)
            results.append({
                "siid": siid,
                "piid": piid,
                "value": value,
                "code": 0 if value is not None else -1,
            })
        return results

    def set_properties_batch(
        self, specs: list[dict],
    ) -> list[dict]:
        results = []
        for spec in specs:
            siid, piid, value = spec["siid"], spec["piid"], spec["value"]
            ok = self.set_property(siid, piid, value)
            results.append({
                "siid": siid,
                "piid": piid,
                "code": 0 if ok else -1,
            })
        return results

    async def execute_action(self, siid: int, aiid: int, params: list | None = None) -> dict:
        action = (siid, aiid)

        if action == Action.START:
            return await self._start_cleaning()
        elif action == Action.PAUSE:
            return self._pause()
        elif action == Action.CHARGE:
            return await self._return_to_dock()
        elif action == Action.STOP:
            return self._stop()
        elif action == Action.START_CUSTOM:
            return await self._start_cleaning()
        elif action == Action.START_WASHING:
            return self._start_washing()
        elif action == Action.START_DRYING:
            return self._start_drying()
        elif action == Action.START_AUTO_EMPTY:
            return self._start_auto_empty()
        else:
            return {"code": -1, "message": f"Unknown action {siid}.{aiid}"}

    async def _start_cleaning(self) -> dict:
        mode = self._properties[Property.CLEANING_MODE]
        if mode == CleaningMode.SWEEPING:
            state = DeviceState.SWEEPING
        elif mode == CleaningMode.MOPPING:
            state = DeviceState.MOPPING
        else:
            state = DeviceState.SWEEP_AND_MOP

        self._set_state(state)
        self._properties[Property.CHARGING_STATUS] = False
        self._notify(Property.CHARGING_STATUS, False)
        self._cleaning_start = time.monotonic()

        if self._cleaning_task and not self._cleaning_task.done():
            self._cleaning_task.cancel()
        self._cleaning_task = asyncio.create_task(self._simulate_cleaning())
        return {"code": 0}

    async def _simulate_cleaning(self) -> None:
        """Simulate a cleaning cycle: clean for ~60s, then return to dock."""
        try:
            for elapsed in range(1, 61):
                await asyncio.sleep(1)
                battery = max(20, 100 - elapsed)
                self._properties[Property.BATTERY_LEVEL] = battery
                self._notify(Property.BATTERY_LEVEL, battery)
                self._properties[Property.CLEANING_TIME] = elapsed
                self._properties[Property.CLEANING_AREA] = elapsed * 2

            await self._return_to_dock()
        except asyncio.CancelledError:
            pass

    async def _return_to_dock(self) -> dict:
        self._set_state(DeviceState.RETURNING)
        if self._cleaning_task and not self._cleaning_task.done():
            self._cleaning_task.cancel()

        await asyncio.sleep(3)
        self._set_state(DeviceState.CHARGING)
        self._properties[Property.CHARGING_STATUS] = True
        self._notify(Property.CHARGING_STATUS, True)

        asyncio.create_task(self._simulate_charging())
        return {"code": 0}

    async def _simulate_charging(self) -> None:
        try:
            while self._properties[Property.BATTERY_LEVEL] < 100:
                await asyncio.sleep(2)
                level = min(100, self._properties[Property.BATTERY_LEVEL] + 1)
                self._properties[Property.BATTERY_LEVEL] = level
                self._notify(Property.BATTERY_LEVEL, level)
            self._set_state(DeviceState.CHARGE_COMPLETE)
        except asyncio.CancelledError:
            pass

    def _pause(self) -> dict:
        if self._cleaning_task and not self._cleaning_task.done():
            self._cleaning_task.cancel()
        self._set_state(DeviceState.PAUSED)
        return {"code": 0}

    def _stop(self) -> dict:
        if self._cleaning_task and not self._cleaning_task.done():
            self._cleaning_task.cancel()
        self._set_state(DeviceState.IDLE)
        return {"code": 0}

    def _start_washing(self) -> dict:
        self._set_state(DeviceState.WASHING)
        return {"code": 0}

    def _start_drying(self) -> dict:
        self._set_state(DeviceState.DRYING)
        return {"code": 0}

    def _start_auto_empty(self) -> dict:
        self._properties[Property.AUTO_EMPTY_STATUS] = 1
        self._notify(Property.AUTO_EMPTY_STATUS, 1)
        return {"code": 0}

    def _set_state(self, state: int) -> None:
        self._properties[Property.STATE] = state
        self._notify(Property.STATE, state)

    def to_device_info(self) -> dict:
        return {
            "did": self.did,
            "name": self.name,
            "model": self.model,
            "mac": self.mac,
            "token": self.token,
            "localip": self.localip,
            "region": self.region,
            "firmware_version": self.firmware_version,
            "feature": 0,
            "property": {},
        }


class DeviceRegistry:
    """Manages all virtual devices."""

    def __init__(self) -> None:
        self._devices: dict[str, VacuumDevice] = {}

    def add(self, device: VacuumDevice) -> None:
        self._devices[device.did] = device

    def get(self, did: str) -> VacuumDevice | None:
        return self._devices.get(did)

    def all(self) -> list[VacuumDevice]:
        return list(self._devices.values())

    def create_default(self) -> VacuumDevice:
        device = VacuumDevice()
        self.add(device)
        return device
