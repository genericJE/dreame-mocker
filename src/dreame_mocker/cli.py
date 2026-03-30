"""CLI entry point for dreame-mocker."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import uvicorn

from .auth import TokenStore
from .mqtt import StatusRelay
from .state import DeviceRegistry, VacuumDevice


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dreame-mocker",
        description="Mock Dreame cloud API server for Home Assistant testing",
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port", type=int, default=13267, help="HTTP API port (default: 13267)",
    )
    parser.add_argument(
        "--mqtt-port", type=int, default=19973, help="MQTT relay port (default: 19973)",
    )
    parser.add_argument(
        "--device-name", default="X50 Ultra Complete",
        help="Virtual device name (default: X50 Ultra Complete)",
    )
    parser.add_argument(
        "--device-model", default="dreame.vacuum.r2532a",
        help="Device model identifier (default: dreame.vacuum.r2532a)",
    )
    parser.add_argument(
        "--device-id", default=None,
        help="Device ID (auto-generated if omitted)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    logger = logging.getLogger("dreame_mocker")

    # --- Build components ---
    registry = DeviceRegistry()
    device = VacuumDevice(
        did=args.device_id,
        name=args.device_name,
        model=args.device_model,
    )
    registry.add(device)

    token_store = TokenStore()
    relay = StatusRelay(host=args.host, port=args.mqtt_port)

    # Wire property changes to MQTT relay
    device.on_property_change(relay.publish_property_change)

    logger.info("Device: %s (did=%s, model=%s)", device.name, device.did, device.model)
    logger.info("HTTP API: http://%s:%d", args.host, args.port)
    logger.info("MQTT relay: %s:%d", args.host, args.mqtt_port)

    # --- Create FastAPI app ---
    from .server import create_app

    app = create_app(registry, token_store)

    @app.on_event("startup")
    async def _start_relay():
        await relay.start()

    @app.on_event("shutdown")
    async def _stop_relay():
        await relay.stop()

    # --- Run ---
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
