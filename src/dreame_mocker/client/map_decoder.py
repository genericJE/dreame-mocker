"""Map download and decode pipeline.

Flow: REQUEST_MAP action -> get download URL -> download -> decode.

Decode pipeline: base64 -> AES-256-CBC decrypt (optional) -> zlib decompress
-> parse 27-byte header + pixel grid + trailing JSON metadata.
"""

# pyright: reportUnknownMemberType=false

from __future__ import annotations

import base64
import hashlib
import json
import logging
import struct
import zlib
from dataclasses import dataclass, field
from typing import Any, cast

from Crypto.Cipher import AES as AES_Mod
from Crypto.Util.Padding import unpad

from dreame_mocker.const import MAP_DOWNLOAD_URL_PATH, SEND_COMMAND_PATH, Action, Property

from .errors import MapDecodeError
from .transport import DreameTransport

logger = logging.getLogger(__name__)

# Header is 27 bytes, all little-endian int16 except frame_type (1 byte).
_HEADER_FMT = "<2hb11h"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 27


@dataclass
class MapHeader:
    """27-byte binary header parsed from a Dreame map frame."""

    map_id: int
    frame_id: int
    frame_type: int  # 73 = I-frame, 80 = P-frame
    robot_x: int
    robot_y: int
    robot_angle: int
    charger_x: int
    charger_y: int
    charger_angle: int
    pixel_size: int  # typically 50 (= 5 cm)
    width: int
    height: int
    left: int
    top: int


@dataclass
class RoomInfo:
    """A room/segment extracted from the map's trailing JSON."""

    segment_id: int
    room_id: int
    name: str
    room_type: int
    neighbors: list[int]


@dataclass
class DreameMap:
    """Fully decoded map data from the robot."""

    header: MapHeader
    pixels: bytes  # raw pixel grid (width * height bytes)
    rooms: dict[int, RoomInfo]
    virtual_walls: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())
    paths: list[list[int]] = field(default_factory=lambda: list[list[int]]())
    obstacles: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())
    raw_metadata: dict[str, Any] = field(default_factory=lambda: dict[str, Any]())

    def room_id_at(self, x: int, y: int) -> int:
        """Return the room/segment ID at pixel (x, y), or 0 if outside."""
        if 0 <= x < self.header.width and 0 <= y < self.header.height:
            return self.pixels[y * self.header.width + x] & 0x3F
        return 0

    def is_wall(self, x: int, y: int) -> bool:
        """Check if the pixel at (x, y) is a wall."""
        if 0 <= x < self.header.width and 0 <= y < self.header.height:
            return bool(self.pixels[y * self.header.width + x] & 0x80)
        return False

    def is_carpet(self, x: int, y: int) -> bool:
        """Check if the pixel at (x, y) is carpet."""
        if 0 <= x < self.header.width and 0 <= y < self.header.height:
            return bool(self.pixels[y * self.header.width + x] & 0x40)
        return False


class MapDecoder:
    """Request, download, and decode map data from the Dreame cloud."""

    @staticmethod
    async def request_and_decode(
        transport: DreameTransport,
        did: str,
        model: str,
        req_type: int = 1,
    ) -> DreameMap:
        """Full map retrieval pipeline."""
        object_name, encryption_key = await MapDecoder.request_map(
            transport, did, req_type=req_type,
        )
        url = await MapDecoder.get_download_url(
            transport, object_name, did, model, transport.region,
        )
        raw = await transport.download(url)
        return MapDecoder.decode(raw, encryption_key)

    @staticmethod
    async def request_map(
        transport: DreameTransport,
        did: str,
        req_type: int = 1,
    ) -> tuple[str, str | None]:
        """Send REQUEST_MAP action.  Returns ``(object_name, encryption_key | None)``.

        ``req_type`` controls which map variant is requested (1 = current, 2 = saved).
        """
        siid, aiid = Action.REQUEST_MAP
        _, frame_piid = Property.FRAME_INFO
        obj_siid, obj_piid = Property.OBJECT_NAME

        resp = await transport.post(
            SEND_COMMAND_PATH,
            json={
                "did": did,
                "id": 1,
                "data": {
                    "did": did,
                    "id": 1,
                    "method": "action",
                    "params": {
                        "did": did,
                        "siid": siid,
                        "aiid": aiid,
                        "in": [
                            {
                                "piid": frame_piid,
                                "value": json.dumps({
                                    "req_type": req_type,
                                    "frame_type": "I",
                                    "force_type": 1,
                                }),
                            },
                        ],
                    },
                },
            },
        )

        body: dict[str, Any] = resp.json()
        raw_data = body.get("data", {})
        result_data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
        raw_result = result_data.get("result", {})
        result: dict[str, Any] = raw_result if isinstance(raw_result, dict) else {}
        out_params: list[dict[str, Any]] = result.get("out", [])

        # Extract object name from response.  The primary location is
        # piid=3 (OBJECT_NAME), but some models (X50 Ultra) return an empty
        # piid=3 and put the path in piid=13 with a ``"<type>,<path>"``
        # format instead.
        object_name = ""
        piid13_value = ""
        for param in out_params:
            piid = param.get("piid")
            val = str(param.get("value", ""))
            if piid == obj_piid and param.get("siid", obj_siid) == obj_siid and val:
                object_name = val
            elif piid == 13 and val:
                piid13_value = val

        if not object_name:
            # Fallback: check if OBJECT_NAME is in a flat result list.
            props: list[dict[str, Any]] = result_data.get("result", []) if isinstance(result_data.get("result"), list) else []
            for p in props:
                if p.get("piid") == obj_piid:
                    object_name = str(p.get("value", ""))
                    break

        if not object_name and piid13_value:
            # piid 13 format: "<type>,<cloud_path>" — strip the leading
            # numeric prefix to get the actual object path.
            object_name = piid13_value

        if not object_name:
            raise MapDecodeError(f"No OBJECT_NAME in REQUEST_MAP response: {body}")

        # Format: "path/to/file,encryption_key" or just "path/to/file"
        # piid 13 variant: "<type>,<path>" where type is a single digit.
        parts = object_name.split(",", 1)
        if len(parts) == 2 and parts[0].isdigit() and "/" in parts[1]:
            # piid 13 format: "1,ali_dreame/..." — the digit is a type
            # prefix, not an encryption key.
            file_path = parts[1]
            enc_key = None
        else:
            file_path = parts[0]
            enc_key = parts[1] if len(parts) > 1 else None

        logger.info("Map object: %s (encrypted=%s)", file_path, enc_key is not None)
        return file_path, enc_key

    @staticmethod
    async def get_download_url(
        transport: DreameTransport,
        filename: str,
        did: str,
        model: str,
        region: str,
    ) -> str:
        """Get a pre-signed download URL for a map file."""
        resp = await transport.post(
            MAP_DOWNLOAD_URL_PATH,
            json={
                "filename": filename,
                "did": did,
                "model": model,
                "region": region,
            },
        )

        body: dict[str, Any] = resp.json()
        url: str = ""
        data: Any = body.get("data", body.get("result", ""))
        if isinstance(data, str):
            url = data
        elif isinstance(data, dict):
            data_d = cast(dict[str, Any], data)
            url = str(data_d.get("url", data_d.get("downloadUrl", "")))

        if not url:
            raise MapDecodeError(f"No download URL in response: {body}")

        return url

    @staticmethod
    def decode(raw_data: bytes, encryption_key: str | None = None) -> DreameMap:
        """Decode raw map bytes through the full pipeline.

        Pipeline: URL-safe base64 -> AES-256-CBC decrypt -> zlib decompress
        -> parse header + pixels + trailing JSON.
        """
        try:
            # Step 1: URL-safe base64 decode.
            b64_str = raw_data.replace(b"-", b"+").replace(b"_", b"/")
            # Pad to multiple of 4.
            padding = 4 - (len(b64_str) % 4)
            if padding != 4:
                b64_str += b"=" * padding
            decoded = base64.b64decode(b64_str)
        except Exception as exc:
            # If base64 fails, the data might already be raw binary.
            logger.debug("Base64 decode failed, trying raw: %s", exc)
            decoded = raw_data

        # Step 2: AES-256-CBC decrypt (if key provided).
        if encryption_key:
            decoded = MapDecoder._aes_decrypt(decoded, encryption_key)

        # Step 3: Zlib decompress.
        try:
            decompressed = zlib.decompress(decoded)
        except zlib.error as exc:
            raise MapDecodeError(f"Zlib decompression failed: {exc}") from exc

        # Step 4: Parse binary structure.
        return MapDecoder._parse(decompressed)

    @staticmethod
    def _aes_decrypt(data: bytes, key_str: str) -> bytes:
        """AES-256-CBC decrypt map data."""
        key_hash = hashlib.sha256(key_str.encode()).hexdigest()
        aes_key = key_hash[:32].encode()

        # The IV is typically the first 16 bytes of the data itself.
        if len(data) < 16:
            raise MapDecodeError("Encrypted data too short for IV extraction")
        iv = data[:16]
        ciphertext = data[16:]

        try:
            cipher = AES_Mod.new(aes_key, AES_Mod.MODE_CBC, iv)
            return unpad(cipher.decrypt(ciphertext), AES_Mod.block_size)
        except (ValueError, KeyError) as exc:
            raise MapDecodeError(f"AES decryption failed: {exc}") from exc

    @staticmethod
    def _parse(data: bytes) -> DreameMap:
        """Parse decompressed map binary into structured data."""
        if len(data) < _HEADER_SIZE:
            raise MapDecodeError(
                f"Map data too small: {len(data)} bytes (need >= {_HEADER_SIZE})"
            )

        # Parse header.
        values = struct.unpack_from(_HEADER_FMT, data)
        header = MapHeader(
            map_id=values[0],
            frame_id=values[1],
            frame_type=values[2],
            robot_x=values[3],
            robot_y=values[4],
            robot_angle=values[5],
            charger_x=values[6],
            charger_y=values[7],
            charger_angle=values[8],
            pixel_size=values[9],
            width=values[10],
            height=values[11],
            left=values[12],
            top=values[13],
        )

        pixel_count = header.width * header.height
        pixel_end = _HEADER_SIZE + pixel_count

        if len(data) < pixel_end:
            raise MapDecodeError(
                f"Map data truncated: {len(data)} bytes, "
                f"expected >= {pixel_end} ({header.width}x{header.height} pixels)"
            )

        pixels = data[_HEADER_SIZE:pixel_end]

        # Parse trailing JSON metadata (if present).
        rooms: dict[int, RoomInfo] = {}
        metadata: dict[str, Any] = {}
        if len(data) > pixel_end:
            try:
                json_bytes = data[pixel_end:]
                metadata = json.loads(json_bytes)
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.debug("No valid JSON metadata after pixel data")

        # Extract room info from seg_inf.
        seg_inf: dict[str, Any] = metadata.get("seg_inf", {})
        for seg_id_str, raw_info in seg_inf.items():
            if not isinstance(raw_info, dict):
                continue
            info = cast(dict[str, Any], raw_info)
            seg_id = int(seg_id_str)
            name_b64 = str(info.get("name", ""))
            try:
                name = base64.b64decode(name_b64).decode("utf-8") if name_b64 else ""
            except Exception:
                name = name_b64
            nei_raw: Any = info.get("nei_id", [])
            nei_ids: list[int] = cast(list[int], nei_raw) if isinstance(nei_raw, list) else []
            rooms[seg_id] = RoomInfo(
                segment_id=seg_id,
                room_id=int(info.get("roomID", seg_id)),
                name=name,
                room_type=int(info.get("type", -1)),
                neighbors=nei_ids,
            )

        logger.info(
            "Map decoded: %dx%d, %d rooms, frame=%s",
            header.width, header.height, len(rooms),
            "I" if header.frame_type == 73 else "P",
        )

        return DreameMap(
            header=header,
            pixels=pixels,
            rooms=rooms,
            virtual_walls=metadata.get("vw", []),
            paths=metadata.get("tr", []),
            obstacles=metadata.get("ai_obstacle", []),
            raw_metadata=metadata,
        )
