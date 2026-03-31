#!/usr/bin/env python3
"""Demo client — authenticates with the real Dreame cloud and controls the robot.

Uses the ``dreame_mocker.client`` library. Tokens are cached to disk so
subsequent runs skip authentication.

Usage:
  uv run python test_client.py                # password login (default)
  uv run python test_client.py --status       # just print status, don't clean
  uv run python test_client.py --map          # fetch and summarise map data
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from dreame_mocker.client import DreameCloud

load_dotenv(interpolate=False)

HOST = os.environ.get("DREAME_HOST", "eu.iot.dreame.tech")
PORT = int(os.environ.get("DREAME_PORT", "13267"))
USERNAME = os.environ["DREAME_USERNAME"]
PASSWORD = os.environ.get("DREAME_PASSWORD", "")
TOKEN_PATH = os.environ.get("DREAME_TOKEN_PATH", "")
REGION = HOST.split(".")[0] if HOST not in ("localhost", "127.0.0.1") else "eu"

logger = logging.getLogger("dreame")

# ── Colored log formatter ────────────────────────────────────────────


class _ColorFormatter(logging.Formatter):
    """Compact colorized formatter with bracketed timestamps."""

    _RESET = "\033[0m"
    _DIM = "\033[2m"
    _BOLD = "\033[1m"

    _LEVEL = {
        logging.DEBUG:    ("\033[36m",    "DBG"),  # cyan
        logging.INFO:     ("\033[32m",    "INF"),  # green
        logging.WARNING:  ("\033[33m",    "WRN"),  # yellow
        logging.ERROR:    ("\033[31m",    "ERR"),  # red
        logging.CRITICAL: ("\033[1;31m",  "CRT"),  # bold red
    }

    def format(self, record: logging.LogRecord) -> str:
        color, tag = self._LEVEL.get(record.levelno, (self._RESET, "???"))

        ts = self.formatTime(record, "%H:%M:%S")

        # Shorten logger names for readability.
        name = record.name
        for prefix in ("dreame_mocker.client.", "dreame_mocker.", "httpx.", "httpcore."):
            if name.startswith(prefix):
                name = name[len(prefix):]
                break

        return (
            f"{self._DIM}[{ts}]{self._RESET} "
            f"{color}{self._BOLD}{tag}{self._RESET} "
            f"{self._DIM}{name:<12}{self._RESET} "
            f"{record.getMessage()}"
        )


def _setup_logging() -> None:
    level = logging.DEBUG if "--debug" in sys.argv else logging.INFO

    handler = logging.StreamHandler()
    handler.setFormatter(_ColorFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

    # Quiet noisy third-party loggers unless --debug.
    if level > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)


# ── Main ─────────────────────────────────────────────────────────────


async def main() -> None:
    _setup_logging()

    status_only = "--status" in sys.argv
    fetch_map = "--map" in sys.argv

    async with DreameCloud(
        username=USERNAME,
        password=PASSWORD or None,
        host=HOST,
        port=PORT,
        token_path=Path(TOKEN_PATH) if TOKEN_PATH else None,
    ) as cloud:
        await cloud.connect()
        logger.info("Connected (uid=%s, region=%s)", cloud.uid, cloud.region)

        device = await cloud.get_device()
        logger.info("Device: %s (did=%s, model=%s)", device.name, device.did, device.model)

        # Read status.
        status = await device.get_status()
        logger.info(
            "Status: %s, Battery: %d%%, Error: %d",
            status.state_name, status.battery, status.error,
        )
        logger.info(
            "  Mode: %d, Suction: %d, Water: %d",
            status.cleaning_mode, status.suction_level, status.water_volume,
        )

        if status_only:
            return

        if fetch_map:
            logger.info("Requesting map...")
            dreame_map = await device.get_map()
            logger.info("Map: %dx%d pixels", dreame_map.header.width, dreame_map.header.height)
            logger.info(
                "  Robot at (%d, %d)", dreame_map.header.robot_x, dreame_map.header.robot_y,
            )
            logger.info(
                "  Charger at (%d, %d)", dreame_map.header.charger_x, dreame_map.header.charger_y,
            )
            if dreame_map.rooms:
                logger.info("  Rooms (%d):", len(dreame_map.rooms))
                for seg_id, room in sorted(dreame_map.rooms.items()):
                    logger.info(
                        "    [%d] %s (type=%d)",
                        seg_id, room.name or f"Room {room.room_id}", room.room_type,
                    )
            return

        # Full demo: start -> poll -> pause -> dock.
        logger.info("Starting clean cycle...")
        await device.start()

        for _ in range(5):
            await asyncio.sleep(2)
            s = await device.get_status()
            logger.info("  -> %s, Battery: %d%%", s.state_name, s.battery)

        logger.info("Pausing...")
        await device.pause()
        await asyncio.sleep(1)
        s = await device.get_status()
        logger.info("  -> %s", s.state_name)

        logger.info("Returning to dock...")
        await device.return_to_dock()
        await asyncio.sleep(4)
        s = await device.get_status()
        logger.info("  -> %s, Battery: %d%%", s.state_name, s.battery)

        logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
