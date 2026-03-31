"""Crypto helpers for the Dreame cloud API.

All crypto operations (AES-ECB, MD5 hashing, request signing) are consolidated
here to isolate PyCryptodome type-stub issues to a single file.
"""

# pyright: reportUnknownMemberType=false

from __future__ import annotations

import base64
import hashlib

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from dreame_mocker.const import AES_KEY, PASSWORD_SALT


def make_dreame_rlc(region: str, lang: str = "en", country: str = "GB") -> str:
    """Build the Dreame-RLC header: AES-ECB encrypt 'region|lang|country'."""
    plaintext = f"{region}|{lang}|{country}"
    cipher = AES.new(AES_KEY, AES.MODE_ECB)
    encrypted: bytes = cipher.encrypt(pad(plaintext.encode(), AES.block_size))
    return base64.b64encode(encrypted).decode()


def hash_password(password: str) -> str:
    """MD5 hash a password with the Dreame salt."""
    salted = password + PASSWORD_SALT
    return hashlib.md5(salted.encode()).hexdigest()


def make_request_sign(params: dict[str, str], timestamp_ms: str) -> str:
    """Build the Dreame request signature (MD5 variant).

    1. Sort params alphabetically (excluding 'sign' and 'timestamp')
    2. Join as key=value&key=value
    3. Append: {timestamp_ms}{salt}  (no reversed salt for MD5)
    4. MD5 hash

    Note: timestamp is NOT included in the sorted params -- it's appended separately.
    The timestamp must be in milliseconds (rounded to nearest second, ends in '000').
    """
    sorted_pairs = "&".join(
        f"{k}={v}" for k, v in sorted(params.items())
        if k not in ("sign", "timestamp")
    )
    salt = AES_KEY.decode()
    raw = f"{sorted_pairs}{timestamp_ms}{salt}"
    return hashlib.md5(raw.encode()).hexdigest()
