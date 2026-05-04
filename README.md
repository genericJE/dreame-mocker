# dreame-mocker

Python client library and mock server for the **Dreame cloud API**. Built to control a **Dreame X50 Ultra Complete** robot vacuum from Home Assistant without depending on the Xiaomi cloud.

The Dreame X50 Ultra Complete is cloud-only -- there is no local control protocol. This project replaces the Dreame phone app, sending the same HTTPS requests to Dreame's cloud servers. It also includes a local mock server for offline development and testing.

## Quick start

```bash
# install
uv sync

# configure credentials
cp .env.example .env
# edit .env with your Dreame account email and password

# run a test action on your real robot
uv run python test_client.py

# or run the local mock server for offline development
uv run dreame-mocker
```

## Authentication

The test client supports two auth methods against the real Dreame cloud:

### Password login (default)

```bash
uv run python test_client.py
```

Requires a Dreame password set on your account (Dreame app > Settings > Account & Security > Password). Works with Google/Apple-linked accounts once a password is added. The password is MD5-hashed with Dreame's salt before transmission.

### Email code login

```bash
uv run python test_client.py --email-code     # interactive (prompts for code)
uv run python test_client.py --code 123456    # non-interactive
```

A verification code is sent to your email. Note: this authenticates to a separate identity from Google/Apple-linked accounts -- your devices may not be visible.

### .env configuration

```bash
DREAME_HOST=                     # empty for real cloud, "localhost" for mock server
DREAME_PORT=13267
DREAME_USERNAME=you@gmail.com
DREAME_PASSWORD=your_password
DREAME_TOKEN_PATH=tokens.json    # token cache location (default: ~/.config/dreame-mocker/tokens.json)
```

When `DREAME_HOST` is empty (default), the client connects to the real Dreame cloud. It authenticates on `eu.iot.dreame.tech` and auto-detects the correct device region from your account's `country` field. Set `DREAME_HOST=localhost` to use the mock server instead.

## How it works

```
+-----------------+         HTTPS       +--------------------+       MQTT        +---------------+
| dreame-mocker   | <=================> | Dreame Cloud API   | <===============> | Your Robot    |
| (this client)   |         :13267      | *.iot.dreame.tech  |                   | X50 Ultra     |
+-----------------+                     +--------------------+                   +---------------+
```

This project replaces the Dreame phone app in that chain. It sends the same HTTPS requests the app would, using reverse-engineered authentication headers and API endpoints.

### Required cloud headers

Every request to the Dreame cloud requires:

| Header | Value |
|--------|-------|
| `Authorization` | `Basic ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg=` |
| `Tenant-Id` | `000000` |
| `Dreame-Meta` | `cv=i_829` |
| `Dreame-Rlc` | AES-ECB encrypted `region\|lang\|country` (key: `EETjszu*XI5znHsI`) |
| `Dreame-Auth` | `bearer <access_token>` |
| `User-Agent` | `Dreame_Smarthome/2.1.9 (iPhone; iOS 18.4.1; Scale/3.00)` |

## Client library

The `dreame_mocker.client` package is a fully async Python library for the Dreame cloud API.

### Usage

```python
from dreame_mocker.client import DreameCloud

async with DreameCloud(username="you@gmail.com", password="secret") as cloud:
    await cloud.connect()

    device = await cloud.get_device()       # first device on account
    status = await device.get_status()       # batch-read state, battery, etc.

    await device.start()                     # start cleaning
    await device.pause()                     # pause
    await device.return_to_dock()            # go home

    dreame_map = await device.get_map()      # download & decode map
    for seg_id, room in dreame_map.rooms.items():
        print(f"Room {seg_id}: {room.name}")
```

### Features

- **Token caching** -- tokens are persisted to `~/.config/dreame-mocker/tokens.json` (0o600 permissions) and reused across runs. Auto-refreshes when within 5 minutes of expiry.
- **Region auto-detection** -- authenticates on any region (default: `eu`), then auto-switches to the correct device region based on your account's `country` field.
- **Retry with backoff** -- transient failures (connect/timeout/transport errors) are retried with exponential backoff (up to 3 attempts). 401s trigger automatic re-authentication.
- **Map decoding** -- full pipeline: base64 > AES-256-CBC decrypt > zlib decompress > parse 27-byte header + pixel grid + trailing JSON (rooms, walls, paths, obstacles).
- **Mock mode** -- when connecting to `localhost`/`127.0.0.1`, cloud-specific headers (Dreame-RLC, Dreame-Meta, etc.) are skipped.

### API reference

**`DreameCloud`** -- main entry point, async context manager.

| Method | Description |
|--------|-------------|
| `connect()` | Authenticate and resolve device region |
| `get_devices()` | List all bound devices (raw dicts) |
| `get_device(did=None)` | Get a `DreameDevice` wrapper (first device if `did` is None) |
| `disconnect()` | Close transport |

**`DreameDevice`** -- typed device wrapper.

| Method | Description |
|--------|-------------|
| `get_status()` | Batch-read state, battery, error, suction, water, mode, time, area |
| `get_state()` / `get_battery()` / `get_error()` | Individual property getters |
| `set_suction_level(level)` / `set_water_volume(vol)` / `set_cleaning_mode(mode)` | Property setters |
| `start()` / `pause()` / `stop()` / `return_to_dock()` | Cleaning actions |
| `start_mop_wash()` / `start_mop_dry()` / `start_dust_collection()` | Dock actions |
| `set_dnd(enabled, start_hour, start_minute, end_hour, end_minute)` | Do Not Disturb config |
| `get_map()` | Download and decode the current map |
| `send_action(siid, aiid, params)` | Low-level action RPC |
| `get_properties(specs)` / `set_properties(specs)` | Low-level property RPC |

**`DreameMap`** -- decoded map data.

| Field / Method | Description |
|----------------|-------------|
| `header` | `MapHeader` with dimensions, robot/charger position, pixel size |
| `pixels` | Raw pixel grid (`width * height` bytes) |
| `rooms` | `dict[int, RoomInfo]` -- segment ID to room info |
| `virtual_walls` / `paths` / `obstacles` | Extracted from trailing JSON metadata |
| `room_id_at(x, y)` | Room/segment ID at pixel coordinate |
| `is_wall(x, y)` / `is_carpet(x, y)` | Pixel type checks |

### Exceptions

All exceptions inherit from `DreameError`:

| Exception | When |
|-----------|------|
| `AuthenticationError` | Login failed or re-auth failed |
| `TokenExpiredError` | Token expired and refresh failed |
| `TokenRevokedError` | Token was revoked server-side |
| `DeviceNotFoundError` | Requested device not on account |
| `DeviceOfflineError` | Device is offline (cloud error -1 or -9999) |
| `RateLimitError` | HTTP 429 (has `.retry_after` attribute) |
| `TransportError` | Network/HTTP errors after retries exhausted |
| `MapDecodeError` | Map download or decode failure |

## API endpoints

### POST `/dreame-auth/oauth/token`

**Password login:**
```
grant_type=password
username=<email>
password=<MD5(password + "RAylYC%fmSKp7%Tq")>
scope=all
platform=IOS
type=account
country=GB
lang=en
```

**Email code login** (two steps):

1. Request code via `POST /dreame-auth/oauth/email` with signed JSON body:
```json
{"email": "<email>", "lang": "en", "sign": "<MD5 signature>", "timestamp": "<ms>"}
```

2. Exchange code for token:
```
grant_type=email&email=<email>&country=GB&lang=en  (query params)
+ headers: Sms-Key=<codeKey>, Sms-Code=<user_code>
```

### POST `/dreame-user-iot/iotuserbind/device/listV2`

Returns all devices bound to your account.

### POST `/dreame-iot-com-10000/device/sendCommand`

Send RPC commands. Supports `get_properties`, `set_properties`, and `action`.

**Example -- start cleaning:**

```json
{
  "did": "<device_id>",
  "id": 1,
  "data": {
    "did": "<device_id>",
    "id": 1,
    "method": "action",
    "params": {"siid": 2, "aiid": 1}
  }
}
```

## Properties reference

All properties are addressed by `(siid, piid)`. See `src/dreame_mocker/const.py` for the full list.

### Device state and battery

| Property | SIID | PIID | Values |
|----------|------|------|--------|
| State | 2 | 1 | 1=Sweeping, 2=Idle, 3=Paused, 4=Error, 5=Returning, 6=Charging, 7=Mopping, 8=Drying, 9=Washing, 12=Sweep+Mop, 13=Charge Complete, 20=Mop Washing, 21=Mop Washing Paused |
| Error | 2 | 2 | 0 = no error |
| Battery level | 3 | 1 | 0-100 |
| Charging status | 3 | 2 | true/false |

#### States observed in practice (X50 Ultra Complete via cloud)

The full state list above is what the firmware can emit. **All non-error states reach the cloud client provided the device's Wi‑Fi is on while the state is active.** Production histories often show only a subset because the device — or a user automation — cuts Wi‑Fi between phases.

Confirmed via two scenarios on a real X50 Ultra Complete (`dreame.vacuum.r2532h`):

**Wi‑Fi held on through the cycle (2026-05-04 manual end-to-end test):**

```
Charge Complete > Washing > Sweep+Mop > Returning > Charging > Washing > Drying
```

All of `Returning` (5), `Charging` (6), and `Drying` (8) emit and reach HA. The full firmware state machine is observable; nothing is hidden by the protocol.

**Wi‑Fi cycled off when "done" (this user's normal operation):**

```
Charge Complete > [Mop Washing >] Sweep+Mop > [device drops off cloud]
```

The cloud poll goes silent before `Returning` / `Charging` / `Drying` emit, because the device or the user's automation has already cut Wi‑Fi. The HA integration then synthesizes an `Offline` value after an unreachability threshold — this is **not** a state the firmware reported, just a stand-in for "we lost the device."

Cleaning-mode-conditional states (`Sweeping`, `Mopping` — the device emits these instead of `Sweep+Mop` when the mode is set to pure-sweep or pure-mop), and user-action-conditional states (`Idle`, `Paused`, `Error`), reach the cloud just like the rest, but only when the corresponding configuration or event occurs.

**Implication for HA / automations.** Prefer `to: Drying` to detect "robot finished active cleaning" — accurate and unambiguous when Wi‑Fi is held on through the cycle. For setups that cut Wi‑Fi before `Drying` would emit, fall back to a transition into the synthetic `Offline` value (the HA integration emits this past the unreachability threshold). Don't use `Charge Complete` as an end-of-cycle trigger — it fires both before and after a clean.

The mock server has an opt-in `--offline-after-return` flag that simulates the Wi‑Fi-cycled scenario, so automations targeting that deployment shape can be exercised against the mock — see [Mock server](#mock-server) below.

### Cleaning settings

| Property | SIID | PIID | Values |
|----------|------|------|--------|
| Cleaning time (s) | 4 | 2 | seconds elapsed |
| Cleaning area (m^2) | 4 | 3 | area cleaned |
| Suction level | 4 | 4 | 0=Quiet, 1=Standard, 2=Strong, 3=Turbo |
| Water volume | 4 | 5 | 1=Low, 2=Medium, 3=High |
| Cleaning mode | 4 | 23 | 0=Sweeping, 1=Mopping, 2=Sweep+Mop |
| Self-wash base status | 4 | 25 | dock station state |

### Consumables

| Property | SIID | PIID | Description |
|----------|------|------|-------------|
| Main brush time left | 9 | 1 | minutes remaining |
| Main brush life | 9 | 2 | percentage |
| Side brush time left | 10 | 1 | minutes remaining |
| Side brush life | 10 | 2 | percentage |
| Filter time left | 11 | 1 | minutes remaining |
| Filter life | 11 | 2 | percentage |
| Mop pad time left | 16 | 1 | minutes remaining |
| Mop pad life | 16 | 2 | percentage |

### Dust collection

| Property | SIID | PIID | Values |
|----------|------|------|--------|
| Dust collection enabled | 15 | 3 | true/false |
| Auto-empty status | 15 | 5 | 0=idle, 1=emptying |

### Do Not Disturb

| Property | SIID | PIID | Values |
|----------|------|------|--------|
| DND enabled | 12 | 1 | true/false |
| DND start hour | 12 | 2 | 0-23 |
| DND start minute | 12 | 3 | 0-59 |
| DND end hour | 12 | 4 | 0-23 |
| DND end minute | 12 | 5 | 0-59 |

### Audio and other

| Property | SIID | PIID | Values |
|----------|------|------|--------|
| Volume | 7 | 1 | 0-100 |
| Timezone | 7 | 5 | IANA timezone string |

## Actions reference

| Action | SIID | AIID | Description |
|--------|------|------|-------------|
| Start | 2 | 1 | Begin cleaning in current cleaning mode |
| Pause | 2 | 2 | Pause current cleaning cycle |
| Charge | 3 | 1 | Return to dock and start charging |
| Start custom | 4 | 1 | Start cleaning (same as Start) |
| Stop | 4 | 2 | Stop cleaning, go idle |
| Start washing | 4 | 4 | Start mop pad wash cycle |
| Start drying | 4 | 5 | Start mop pad drying |
| Auto-empty | 15 | 1 | Trigger dustbin auto-empty |

## Mock server

For offline development, the built-in mock server simulates the Dreame cloud API locally:

```bash
uv run dreame-mocker --log-level DEBUG
```

This starts:
- HTTP API on `:13267` (same endpoints as the real cloud)
- TCP status relay on `:19973` (pushes property changes)

The mock includes a full device state machine: cleaning cycles with battery drain, dock return, charging, mop wash/dry, and dust collection. Point your `.env` at `localhost` to use it:

```bash
DREAME_HOST=localhost
DREAME_PORT=13267
```

### Wi‑Fi-cycled mode (`--offline-after-return`)

The default mock cycle (`SWEEP_AND_MOP > RETURNING > CHARGING > CHARGE_COMPLETE`, all online) is what a real X50 emits when Wi‑Fi is held on through the whole cycle — empirically verified, see [States observed in practice](#states-observed-in-practice-x50-ultra-complete-via-cloud). Many production setups, however, cut Wi‑Fi as soon as the robot is "done", so HA never sees `RETURNING` / `CHARGING` / `DRYING` in those deployments.

Pass `--offline-after-return` to simulate the Wi‑Fi-cycled deployment shape:

```bash
uv run dreame-mocker --offline-after-return --offline-duration 60
```

After cleaning finishes the device briefly enters `RETURNING`, then RPC calls return `code=-1` (which the client surfaces as `DeviceOfflineError`) for `--offline-duration` seconds. When the offline window ends, the device reappears in `CHARGE_COMPLETE` directly — `CHARGING` and `DRYING` are skipped because the simulated Wi‑Fi was off while the firmware was in those states. Use this mode to test "robot done" automations targeting Wi‑Fi-cycled deployments before deploying them against the real cloud in such a setup.

The default Wi‑Fi-on cycle is preserved when the flag is omitted, so existing tests don't change.

### CLI flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--host` | string | `0.0.0.0` | Bind address |
| `--port` | int | `13267` | HTTP API port |
| `--mqtt-port` | int | `19973` | Status relay port |
| `--device-name` | string | `X50 Ultra Complete` | Virtual device display name |
| `--device-model` | string | `dreame.vacuum.r2532a` | Model identifier |
| `--device-id` | string | auto-generated | Device ID |
| `--log-level` | choice | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `--offline-after-return` | flag | off | Simulate Wi-Fi-cycled deployment: drop off after RETURNING, hide CHARGING / DRYING, reappear as CHARGE_COMPLETE |
| `--offline-duration` | float | `60.0` | Seconds the simulated device stays offline (only with `--offline-after-return`) |

### Map support

The mock server generates synthetic map data with rooms, walls, and robot/charger positions. Maps are served through the same endpoints as the real cloud (request map action > get download URL > download encoded map file).

## Supported X50 Ultra Complete model variants

- `dreame.vacuum.r2532a` (default)
- `dreame.vacuum.r2532d`
- `dreame.vacuum.r2532h`
- `dreame.vacuum.r2532v`
- `dreame.vacuum.r2532z`
- `dreame.vacuum.r2538a`
- `dreame.vacuum.r2538z`

## Development

```bash
uv sync                              # install deps
uv run pyright                        # type check (strict mode, 0 errors)
uv run dreame-mocker --log-level DEBUG  # run mock server
uv run python test_client.py          # test against real cloud
uv run python test_client.py --status # read-only status check
uv run python test_client.py --map    # fetch and summarize map data
```

## Project structure

```
test_client.py                  # real-cloud demo client
src/dreame_mocker/
  __init__.py                   # package root (re-exports DreameCloud, DreameDevice)
  const.py                      # SIID/PIID/AIID mappings, enums, API paths
  client/                       # async cloud client library
    __init__.py                 # public API re-exports
    auth.py                     # AuthManager -- login, token refresh, caching
    cloud.py                    # DreameCloud -- main entry point, region detection
    crypto.py                   # Dreame-RLC encryption, password hashing, request signing
    device.py                   # DreameDevice -- typed property/action interface
    errors.py                   # exception hierarchy
    map_decoder.py              # map download, AES decrypt, zlib decompress, binary parse
    regions.py                  # country-to-region mapping, URL helpers
    tokens.py                   # TokenStore -- disk-persisted token cache
    transport.py                # DreameTransport -- httpx wrapper with retry/backoff
  models.py                     # Pydantic request/response models (mock server)
  state.py                      # device state machine (mock server)
  auth.py                       # OAuth2 mock token store (mock server)
  server.py                     # FastAPI mock server
  map_encoder.py                # synthetic map data generator (mock server)
  mqtt.py                       # TCP status relay (mock server)
  cli.py                        # mock server CLI entry point
```
