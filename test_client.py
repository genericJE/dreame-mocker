#!/usr/bin/env python3
"""Test client — authenticates with the real Dreame cloud and runs a robot action.

Supports two auth methods:
  1. Email code login (default) — a verification code is sent to your email.
     Works with Google/Apple-linked accounts. No password needed.
  2. Password login — for accounts with a Dreame password set.

Usage:
  uv run python test_client.py              # email code login (interactive)
  uv run python test_client.py --password   # password login
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys
import time
from typing import Any

import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from dotenv import load_dotenv

load_dotenv(interpolate=False)

HOST = os.environ["DREAME_HOST"]
PORT = os.environ["DREAME_PORT"]
USERNAME = os.environ["DREAME_USERNAME"]
PASSWORD = os.environ.get("DREAME_PASSWORD", "")

IS_REAL_CLOUD = HOST != "localhost" and HOST != "127.0.0.1"
SCHEME = "https" if IS_REAL_CLOUD else "http"
BASE = f"{SCHEME}://{HOST}:{PORT}"

# --- Dreame cloud constants ---
DREAME_PASSWORD_SALT = "RAylYC%fmSKp7%Tq"
DREAME_CLIENT_CREDENTIALS_B64 = "ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg="
DREAME_AES_KEY = b"EETjszu*XI5znHsI"

# Derive region from host: eu.iot.dreame.tech -> eu
REGION = HOST.split(".")[0] if IS_REAL_CLOUD else "eu"

STATES: dict[int, str] = {
    1: "Sweeping",
    2: "Idle",
    3: "Paused",
    4: "Error",
    5: "Returning",
    6: "Charging",
    7: "Mopping",
    8: "Drying",
    9: "Washing",
    12: "Sweep+Mop",
    13: "Charge Complete",
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


# --- Crypto helpers ---

def make_dreame_rlc(region: str, lang: str = "en", country: str = "GB") -> str:
    """Build the Dreame-RLC header: AES-ECB encrypt 'region|lang|country'."""
    plaintext = f"{region}|{lang}|{country}"
    cipher = AES.new(DREAME_AES_KEY, AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(plaintext.encode(), AES.block_size))
    return base64.b64encode(encrypted).decode()


def hash_password(password: str) -> str:
    """MD5 hash password with the Dreame salt."""
    salted = password + DREAME_PASSWORD_SALT
    return hashlib.md5(salted.encode()).hexdigest()


# --- Request helpers ---

def build_headers(token: str | None = None) -> dict[str, str]:
    """Build request headers for mock or real cloud."""
    if not IS_REAL_CLOUD:
        if token:
            return {"Authorization": f"Bearer {token}"}
        return {}

    headers = {
        "Authorization": f"Basic {DREAME_CLIENT_CREDENTIALS_B64}",
        "Tenant-Id": "000000",
        "Dreame-Meta": "cv=i_829",
        "Dreame-Rlc": make_dreame_rlc(REGION),
        "User-Agent": "Dreame_Smarthome/2.1.9 (iPhone; iOS 18.4.1; Scale/3.00)",
        "Dreame-Auth": f"bearer {token}" if token else "bearer",
    }
    return headers


# --- Auth flows ---

def request_email_code(client: httpx.Client) -> tuple[str, str]:
    """Request a verification code to be sent to the user's email.
    Returns (sms_key, sms_code_placeholder)."""
    log(f"Sending verification code to {USERNAME}...")
    resp = client.post(
        "/dreame-user/v2/register/email/code",
        headers=build_headers(),
        json={"email": USERNAME},
    )

    if resp.status_code != 200:
        # Try alternate path used by some regions
        resp = client.post(
            "/api/dreame-user/v2/register/email/code",
            headers=build_headers(),
            json={"email": USERNAME},
        )

    if resp.status_code != 200:
        log(f"Failed to send code: {resp.status_code}")
        log(f"Response: {resp.text}")
        sys.exit(1)

    body = resp.json()
    sms_key: str = body.get("sms_key", body.get("data", {}).get("sms_key", ""))
    log("Verification code sent! Check your email.")
    return sms_key, ""


def authenticate_email_code(client: httpx.Client) -> str:
    """Email code login: send code to email, user enters it, exchange for token."""
    sms_key, _ = request_email_code(client)

    code = input("Enter the code from your email: ").strip()

    headers = build_headers()
    headers["Sms-Key"] = sms_key
    headers["Sms-Code"] = code

    resp = client.post(
        "/dreame-auth/oauth/token",
        headers=headers,
        data={
            "grant_type": "email",
            "email": USERNAME,
            "scope": "all",
            "platform": "IOS",
            "country": "GB",
            "lang": "en",
        },
    )

    if resp.status_code != 200:
        log(f"Email code auth failed: {resp.status_code}")
        log(f"Response: {resp.text}")
        sys.exit(1)

    token: str = resp.json()["access_token"]
    return token


def authenticate_password(client: httpx.Client) -> str:
    """Password login with MD5-hashed password."""
    if not PASSWORD:
        log("DREAME_PASSWORD not set in .env")
        sys.exit(1)

    hashed_pw = hash_password(PASSWORD)
    resp = client.post(
        "/dreame-auth/oauth/token",
        headers=build_headers(),
        data={
            "grant_type": "password",
            "scope": "all",
            "platform": "IOS",
            "type": "account",
            "username": USERNAME,
            "password": hashed_pw,
            "country": "GB",
            "lang": "en",
        },
    )

    if resp.status_code != 200:
        log(f"Password auth failed: {resp.status_code}")
        log(f"Response: {resp.text}")
        sys.exit(1)

    token: str = resp.json()["access_token"]
    return token


def authenticate_mock(client: httpx.Client) -> str:
    """Simple auth against the local mock server."""
    resp = client.post(
        "/dreame-auth/oauth/token",
        data={
            "grant_type": "password",
            "username": USERNAME,
            "password": PASSWORD,
        },
    )
    resp.raise_for_status()
    token: str = resp.json()["access_token"]
    return token


# --- API calls ---

def send_action(
    client: httpx.Client,
    headers: dict[str, str],
    did: str,
    siid: int,
    aiid: int,
) -> dict[str, Any]:
    resp = client.post(
        "/dreame-iot-com-10000/device/sendCommand",
        headers=headers,
        json={
            "did": did,
            "id": 1,
            "data": {
                "did": did,
                "id": 1,
                "method": "action",
                "params": {"siid": siid, "aiid": aiid},
            },
        },
    )
    resp.raise_for_status()
    result: dict[str, Any] = resp.json()
    return result


def get_status(
    client: httpx.Client,
    headers: dict[str, str],
    did: str,
) -> tuple[int, int]:
    resp = client.post(
        "/dreame-iot-com-10000/device/sendCommand",
        headers=headers,
        json={
            "did": did,
            "id": 1,
            "data": {
                "did": did,
                "id": 1,
                "method": "get_properties",
                "params": [
                    {"siid": 2, "piid": 1},
                    {"siid": 3, "piid": 1},
                ],
            },
        },
    )
    resp.raise_for_status()
    props: list[dict[str, int]] = resp.json()["data"]["result"]
    state = props[0]["value"]
    battery = props[1]["value"]
    return state, battery


# --- Main ---

def main() -> None:
    use_password = "--password" in sys.argv
    log(f"Target: {BASE} ({'real cloud' if IS_REAL_CLOUD else 'local mock'})")

    client = httpx.Client(base_url=BASE, timeout=15)

    # --- 1. Authenticate ---
    log("Authenticating...")
    if not IS_REAL_CLOUD:
        token = authenticate_mock(client)
    elif use_password:
        token = authenticate_password(client)
    else:
        token = authenticate_email_code(client)
    log(f"Authenticated (token: {token[:12]}...)")

    headers = build_headers(token)

    # --- 2. List devices ---
    log("Fetching devices...")
    resp = client.post(
        "/dreame-user-iot/iotuserbind/device/listV2",
        headers=headers,
    )
    if resp.status_code != 200:
        log(f"Device list failed: {resp.status_code}")
        log(f"Response: {resp.text}")
        sys.exit(1)

    body = resp.json()
    devices: list[dict[str, str]] = body.get("data", body.get("result", []))
    if not devices:
        log("No devices found!")
        log(f"Full response: {body}")
        sys.exit(1)

    did = devices[0]["did"]
    name = devices[0].get("name", devices[0].get("model", "Unknown"))
    model = devices[0].get("model", "Unknown")
    log(f"Found: {name} (did={did}, model={model})")

    # --- 3. Read current state ---
    state, battery = get_status(client, headers, did)
    log(f"Status: {STATES.get(state, str(state))}, Battery: {battery}%")

    # --- 4. Start cleaning ---
    log("Starting clean cycle...")
    result = send_action(client, headers, did, siid=2, aiid=1)
    log(f"  Result: {result}")

    # --- 5. Poll state ---
    for _ in range(5):
        time.sleep(2)
        state, battery = get_status(client, headers, did)
        log(f"  -> {STATES.get(state, str(state))}, Battery: {battery}%")

    # --- 6. Pause ---
    log("Pausing...")
    send_action(client, headers, did, siid=2, aiid=2)
    time.sleep(1)
    state, _ = get_status(client, headers, did)
    log(f"  -> {STATES.get(state, str(state))}")

    # --- 7. Return to dock ---
    log("Returning to dock...")
    send_action(client, headers, did, siid=3, aiid=1)
    time.sleep(4)
    state, battery = get_status(client, headers, did)
    log(f"  -> {STATES.get(state, str(state))}, Battery: {battery}%")

    log("Done.")
    client.close()


if __name__ == "__main__":
    main()
