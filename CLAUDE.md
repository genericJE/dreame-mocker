# Claude Code Instructions

## Directives

- **NEVER read, display, or access `.env`** — it contains user credentials. Do not use the Read tool, Bash cat/head/tail, or any other method to view its contents.
- `CLAUDE.local.md` contains user-specific info (device ID, email, account country, region routing). It is gitignored. Read it when needed for debugging but never commit it.
- **Keep `README.md` up-to-date** — whenever you add features, change APIs, fix bugs, or discover new information, update the README to reflect the current state of the project.
- **Keep this file (`CLAUDE.md`) up-to-date** — record all research findings, API discoveries, architectural decisions, and technical explanations here so knowledge persists across sessions.

## Project context

- This is a Python project managed with `uv` (Python 3.13)
- Type checking uses `pyright` in strict mode (see `pyrightconfig.json`) — includes both `src/dreame_mocker/` and `test_client.py`
- This project mocks the **Dreame mobile app** (not the cloud server) — it acts as a client that talks to the real Dreame cloud API to control a Dreame X50 Ultra Complete robot vacuum
- The project also includes a local mock server for offline development/testing
- The X50 Ultra Complete is **cloud-only** — there is no local control protocol, no local API, no way to bypass the cloud

## Commands

- `uv run python test_client.py` — run the real-cloud test client (password auth by default)
- `uv run python test_client.py --email-code` — email code auth (interactive)
- `uv run python test_client.py --code 123456` — email code auth (non-interactive)
- `uv run dreame-mocker` — run the local mock server
- `uv run pyright` — type check (must be 0 errors)

## Dreame cloud API research

### Base URL

`https://{region}.iot.dreame.tech:13267` where region is `eu`, `us`, or `cn`.

### Authentication

#### Client credentials (always required)

- `Authorization: Basic ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg=` (decodes to `dreame_appv1:AP^dv@z@SQYVxN88`)

#### Required headers (every request)

| Header | Value |
|--------|-------|
| `Authorization` | `Basic ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg=` |
| `Tenant-Id` | `000000` |
| `Dreame-Meta` | `cv=i_829` |
| `Dreame-Rlc` | AES-ECB encrypted `region\|lang\|country` (key: `EETjszu*XI5znHsI`) |
| `Dreame-Auth` | `bearer <access_token>` (after auth) |
| `User-Agent` | `Dreame_Smarthome/2.1.9 (iPhone; iOS 18.4.1; Scale/3.00)` |

#### Password login (`grant_type=password`)

- Endpoint: `POST /dreame-auth/oauth/token`
- Content-Type: `application/x-www-form-urlencoded`
- Password hashing: `MD5(password + "RAylYC%fmSKp7%Tq")`
- Works with Google/Apple-linked accounts **only if a Dreame password has been set** (Dreame app → Settings → Account & Security → Password)

#### Email code login (`grant_type=email`)

Two-step flow:

1. **Request code**: `POST /dreame-auth/oauth/email` with JSON body `{email, lang, sign, timestamp}`
   - Sign computation: `MD5(sorted_params + timestamp_ms + "EETjszu*XI5znHsI")`
   - `sorted_params` = alphabetically sorted `key=value` pairs joined by `&`, excluding `sign` and `timestamp`
   - Timestamp is milliseconds (rounded to nearest second, ends in `000`)
   - Response: `{"data": {"codeKey": "..."}}`

2. **Exchange code**: `POST /dreame-auth/oauth/token` with query params `grant_type=email&email=...&country=GB&lang=en` and headers `Sms-Key: <codeKey>`, `Sms-Code: <user_code>`

**Important**: Email code login authenticates to a **separate identity** from Google/Apple-linked accounts. Devices bound to a Google-linked account will NOT appear. Use password login instead.

#### Region auto-detection

The token response includes `country` (e.g. `"US"`). Devices live on the region matching the account country, NOT necessarily the auth endpoint region. The client auto-switches: auth on `eu.iot.dreame.tech` → devices on `us.iot.dreame.tech`.

### API endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/dreame-auth/oauth/token` | POST | Login / token refresh |
| `/dreame-auth/oauth/email` | POST | Request email verification code |
| `/dreame-user-iot/iotuserbind/device/listV2` | POST | List bound devices |
| `/dreame-iot-com-10000/device/sendCommand` | POST | Send RPC (get_properties, set_properties, action) |
| `/dreame-user-iot/iotfile/getDownloadUrl` | POST | Get pre-signed URL for map file download |

### Device list response format

```json
{"data": {"page": {"records": [{...device...}]}}}
```

Device fields include: `did`, `model`, `subModel`, `ver`, `customName`, `mac`, `sn`, `master`, `property` (JSON string with `iotId`, `lwt`, `mac`).

### RPC command format

```json
{
  "did": "<device_id>",
  "id": 1,
  "data": {
    "did": "<device_id>",
    "id": 1,
    "method": "action|get_properties|set_properties",
    "params": {...}
  }
}
```

### Device states

| Value | State |
|-------|-------|
| 1 | Sweeping |
| 2 | Idle |
| 3 | Paused |
| 4 | Error |
| 5 | Returning |
| 6 | Charging |
| 7 | Mopping |
| 8 | Drying |
| 9 | Washing |
| 12 | Sweep+Mop |
| 13 | Charge Complete |
| 20 | Mop Washing |
| 21 | Mop Washing Paused |

### Map data (SIID 6)

#### Properties

| PIID | Name | Description |
|------|------|-------------|
| 1 | MAP_DATA | Encoded map data (pushed via MQTT or polled) |
| 2 | FRAME_INFO | Frame request/response info |
| 3 | OBJECT_NAME | Cloud storage file identifier + optional AES key |
| 4 | MAP_EXTEND_DATA | Extended map data (map switching) |
| 5 | ROBOT_TIME | Timestamp |
| 6 | RESULT_CODE | Result code for map operations |
| 7 | MULTI_FLOOR_MAP | Whether multi-floor map is enabled |
| 8 | MAP_LIST | JSON list of saved maps with object names |
| 9 | RECOVERY_MAP_LIST | Recovery/backup maps |

#### Actions

| AIID | Name | Description |
|------|------|-------------|
| 1 | REQUEST_MAP | Trigger robot to upload current map to cloud |
| 2 | UPDATE_MAP_DATA | Send map modifications (zones, walls, room edits) |

#### Map retrieval flow

1. Call `REQUEST_MAP` action (SIID 6, AIID 1) with `FRAME_INFO` param: `{"req_type":1,"frame_type":"I","force_type":1}`
2. Response includes `OBJECT_NAME` (PIID 3): `"<cloud_path>,<encryption_key>"` (comma-separated)
3. Get download URL: `POST /dreame-user-iot/iotfile/getDownloadUrl` with `{filename, did, model, region}`
4. Download the file from the pre-signed URL

#### Map data encoding pipeline

1. URL-safe Base64 substitution: `-` → `+`, `_` → `/`
2. Base64 decode
3. AES-256-CBC decryption (if encryption key provided): key = `SHA256(encryption_key).hex()[0:32]`, IV is model-specific
4. Zlib decompression

#### Map binary format

- **Header**: 27 bytes (little-endian): map_id, frame_id, frame_type, robot_x/y/angle, charger_x/y/angle, pixel_size, width, height, left, top
- **Pixel data**: `width × height` bytes. Bits 0-5 = room ID, bit 6 = carpet, bit 7 = wall
- **Trailing JSON**: room info (`seg_inf`), cleaning settings (`cleanset`), virtual walls (`vw`), path (`tr`), obstacles (`ai_obstacle`)

#### Room identification

In `seg_inf`, each room has: `nei_id` (neighbors), `type` (room type int), `index`, `roomID`, `name` (Base64-encoded UTF-8)

### MQTT live updates

Real-time property updates (including map data during cleaning) are pushed via MQTT at `mqtts://{region}.iot.dreame.tech:19973`. Topic: `/status/{did}/{uid}/{model}/{region}/`.

### Crypto constants

| Constant | Value | Usage |
|----------|-------|-------|
| AES key | `EETjszu*XI5znHsI` | Dreame-RLC header encryption, request signing |
| Password salt | `RAylYC%fmSKp7%Tq` | MD5 password hashing |
| Client credentials | `dreame_appv1:AP^dv@z@SQYVxN88` | Basic auth header |

### Sign algorithm variants

| Variant | Hash | Salt appended | Used for |
|---------|------|---------------|----------|
| MD5 (manual) | MD5 | `{sorted_params}{timestamp_ms}{salt}` | `/dreame-auth/oauth/email` |
| SHA384 (v2) | SHA384 | `{sorted_params}{timestamp_ms}{salt}{reversed_salt}` | SMS endpoints |

### Web portal

The Dreame web account portal at `eu-account.dreame.tech` uses the same API with `/api/` prefix. JavaScript bundles contain endpoint definitions and signing logic. Main bundle: `/static/js/app.66513d9a.js`. Login logic: `/static/js/chunk-d8a3fbac.89ed3673.js`.

## Client library architecture (`dreame_mocker.client`)

The client library is a fully async Python library in `src/dreame_mocker/client/` with 10 modules:

| Module | Class | Responsibility |
|--------|-------|----------------|
| `cloud.py` | `DreameCloud` | Main entry point, async context manager, region auto-detection |
| `device.py` | `DreameDevice` | Typed property getters/setters, actions, map retrieval |
| `auth.py` | `AuthManager` | Password/email-code login, token refresh, thread-safe with `asyncio.Lock` |
| `transport.py` | `DreameTransport` | `httpx.AsyncClient` wrapper, injects headers, tenacity retry on transient failures |
| `map_decoder.py` | `MapDecoder` | Full map pipeline: request → download → base64 → AES → zlib → parse |
| `tokens.py` | `TokenStore` | Disk-persisted token cache at `~/.config/dreame-mocker/tokens.json` (0o600) |
| `crypto.py` | — | `make_dreame_rlc()`, `hash_password()`, `make_request_sign()` |
| `regions.py` | — | Country→region mapping, `base_url()`, `region_from_host()` |
| `errors.py` | — | Exception hierarchy rooted at `DreameError` |
| `__init__.py` | — | Public re-exports |

### Key design decisions

- **Token auto-refresh**: `auth.ensure_valid_token()` is called before every API request. If the token is within 5 minutes of expiry, it refreshes automatically.
- **Retry strategy**: Tenacity with 3 attempts, exponential backoff 1–30s with jitter, on `ConnectError`/`ReadTimeout`/`WriteTimeout`/`PoolTimeout`/`TransportError`. 401s trigger re-auth (not retry). 429s raise `RateLimitError`.
- **Region switching**: `transport.switch_region()` closes the old `httpx.AsyncClient` and creates a new one pointed at the correct host.
- **Mock mode**: When `host` is `localhost`/`127.0.0.1`, cloud headers (Dreame-RLC, Dreame-Meta, etc.) are skipped.
- **`_rpc()` auto-retry on 401**: The `DreameDevice._rpc()` method retries once on HTTP 401 after re-authenticating.

## Architectural decisions

- **Password login as default**: Email code login creates a separate identity from Google/Apple OAuth-linked accounts, so devices don't appear. Password login authenticates to the same account.
- **Region auto-detection**: Auth can happen on any region, but device APIs must use the region matching the account's `country` field.
- **Mock server kept**: `mqtt.py` and the mock server are useful for offline development even though the real robot is cloud-only. The mock server simulates the Dreame cloud API locally with a state machine.


## Known limitations

- The X50 Ultra Complete has **no local control** — all commands require cloud connectivity
- No known root method for the X50 Ultra to enable local MQTT yet
- Valetudo does not support the X50 Ultra Complete
- Password auth has a rate limit — too many wrong attempts will lock the account
- Map data AES-256-CBC decryption requires a model-specific IV (stored in Tasshack's `DEVICE_MAP_KEY` constant)

## Open-source references

- [Tasshack/dreame-vacuum](https://github.com/Tasshack/dreame-vacuum) — HA integration, uses Xiaomi cloud, has map decoding
- [TA2k/ioBroker.dreame](https://github.com/TA2k/ioBroker.dreame) — uses Dreame-native API, password login only
- [spayrosam/ioBroker.dreamehome](https://github.com/spayrosam/ioBroker.dreamehome) — Dreame-native, password only
- [pgrootkop-cmyk/com.dreame.vacuum.cloud](https://github.com/pgrootkop-cmyk/com.dreame.vacuum.cloud) — Homey app, password only
