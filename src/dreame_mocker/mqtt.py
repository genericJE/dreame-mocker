"""Lightweight MQTT status publisher using gmqtt (client-side).

For a full mock we'd need a broker. This module provides a simple asyncio-based
MQTT publisher that can connect to a local broker (e.g. Mosquitto) and push
device status updates — mirroring how the real Dreame cloud pushes updates.

It also includes a minimal in-process "broker" using plain TCP + asyncio for
self-contained testing without an external broker.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
from typing import Any

logger = logging.getLogger("dreame_mocker.mqtt")

# --- Minimal in-process MQTT-like status relay ---


class StatusRelay:
    """In-process pub/sub relay that mimics the Dreame MQTT status channel.

    Clients (e.g. Home Assistant integration) can connect over plain TCP.
    Messages are JSON-encoded device property updates pushed on change.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 19973) -> None:
        self.host = host
        self.port = port
        self._subscribers: list[asyncio.StreamWriter] = []
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port,
        )
        logger.info("MQTT status relay listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for writer in self._subscribers:
            writer.close()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ) -> None:
        addr = writer.get_extra_info("peername")
        logger.info("Status relay client connected: %s", addr)
        self._subscribers.append(writer)
        try:
            # Keep connection open; we only push to clients
            while True:
                data = await reader.read(1024)
                if not data:
                    break
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self._subscribers.remove(writer)
            writer.close()
            logger.info("Status relay client disconnected: %s", addr)

    def publish_property_change(
        self, did: str, siid: int, piid: int, value: Any,
    ) -> None:
        message = json.dumps({
            "did": did,
            "siid": siid,
            "piid": piid,
            "value": value,
        })
        payload = message.encode()
        # Length-prefixed framing: 4-byte big-endian length + payload
        frame = struct.pack(">I", len(payload)) + payload
        dead: list[asyncio.StreamWriter] = []
        for writer in self._subscribers:
            try:
                writer.write(frame)
            except (ConnectionError, RuntimeError):
                dead.append(writer)
        for w in dead:
            self._subscribers.remove(w)
