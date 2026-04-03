"""Generate a mock map binary for the simulated vacuum.

Encoding pipeline (reverse of map_decoder): build binary -> zlib compress
-> URL-safe base64 encode.  No AES encryption for simplicity.
"""

from __future__ import annotations

import base64
import json
import struct
import zlib


_HEADER_FMT = "<2hb11h"

# Room pixel values (bits 0-5 = room ID, bit 7 = wall)
_WALL = 0x80
_EMPTY = 0x00


def _b64_room(name: str) -> str:
    return base64.b64encode(name.encode()).decode()


def generate_mock_map() -> bytes:
    """Build a 100x80 four-room apartment map, encoded and ready to serve.

    Layout (100 wide x 80 tall)::

        +----------------------------------------------------+
        |              |                                      |
        |   Living     |          Bedroom                     |
        |   Room (1)   |            (2)                       |
        |              |                                      |
        |----    ------+------    ----------------------------|
        |              |                                      |
        |  Kitchen (3) |       Bathroom (4)                   |
        |              |                                      |
        +----------------------------------------------------+

    Charger at (10, 10), robot at charger.
    """
    width, height = 100, 80
    pixels = bytearray(width * height)

    # Fill rooms
    for y in range(height):
        for x in range(width):
            # Outer walls
            if x == 0 or x == width - 1 or y == 0 or y == height - 1:
                pixels[y * width + x] = _WALL
                continue

            # Horizontal divider at y=45
            if y == 45 and not (20 <= x <= 24 or 55 <= x <= 59):
                pixels[y * width + x] = _WALL
                continue

            # Vertical divider at x=40
            if x == 40 and not (18 <= y <= 22 or 50 <= y <= 54):
                pixels[y * width + x] = _WALL
                continue

            # Assign rooms
            if y < 45:
                room_id = 1 if x < 40 else 2
            else:
                room_id = 3 if x < 40 else 4

            pixels[y * width + x] = room_id

    header = struct.pack(
        _HEADER_FMT,
        1,     # map_id
        1,     # frame_id
        73,    # frame_type (I-frame)
        10,    # robot_x
        10,    # robot_y
        0,     # robot_angle
        10,    # charger_x
        10,    # charger_y
        0,     # charger_angle
        50,    # pixel_size (5cm per pixel)
        width,
        height,
        0,     # left
        0,     # top
    )

    metadata = json.dumps({
        "seg_inf": {
            "1": {
                "roomID": 1,
                "name": _b64_room("Living Room"),
                "type": 0,
                "index": 0,
                "nei_id": [2, 3],
            },
            "2": {
                "roomID": 2,
                "name": _b64_room("Bedroom"),
                "type": 1,
                "index": 1,
                "nei_id": [1, 4],
            },
            "3": {
                "roomID": 3,
                "name": _b64_room("Kitchen"),
                "type": 2,
                "index": 2,
                "nei_id": [1, 4],
            },
            "4": {
                "roomID": 4,
                "name": _b64_room("Bathroom"),
                "type": 3,
                "index": 3,
                "nei_id": [2, 3],
            },
        },
    }).encode()

    raw = header + bytes(pixels) + metadata
    compressed = zlib.compress(raw)
    b64 = base64.b64encode(compressed)
    return b64.replace(b"+", b"-").replace(b"/", b"_").rstrip(b"=")
