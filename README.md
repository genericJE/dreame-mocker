# dreame-mocker

Python client that mocks the **Dreame mobile app** to control a **Dreame X50 Ultra Complete** robot vacuum via the Dreame cloud API. Built for Home Assistant automation development.

The Dreame X50 Ultra Complete is cloud-only — there is no local control protocol. This project acts as the phone app, talking to Dreame's real cloud servers to send commands to your robot. It also includes a local mock server for offline development and testing.

## Quick start

```bash
# install
uv sync

# configure credentials
cp .env.example .env
# edit .env with your Dreame account email

# authenticate and run a test action on your real robot
uv run python test_client.py

# or run the local mock server for offline development
uv run dreame-mocker
```

## Authentication

The test client supports two auth methods against the real Dreame cloud:

### Email code login (default, works with Google/Apple accounts)

```bash
uv run python test_client.py
```

A verification code is sent to your email. Enter it at the prompt and you're in. No Dreame password needed — this works even if you signed up via Google or Apple.

### Password login

```bash
uv run python test_client.py --password
```

Requires a Dreame password set on your account. The password is MD5-hashed with Dreame's salt before transmission.

### .env configuration

```bash
DREAME_HOST=eu.iot.dreame.tech    # eu / us / cn region
DREAME_PORT=13267
DREAME_USERNAME=you@gmail.com
DREAME_PASSWORD=                   # optional, only for --password mode
```

## How it works

The Dreame X50 Ultra Complete communicates exclusively through Dreame's cloud:

```
┌─────────────┐        HTTPS        ┌──────────────────┐       MQTT       ┌─────────────┐
│ dreame-mocker│ ◄──────────────────► │ Dreame Cloud API │ ◄───────────────► │ Your Robot  │
│ (this client)│   :13267             │ *.iot.dreame.tech│                   │ X50 Ultra   │
└─────────────┘                      └──────────────────┘                   └─────────────┘
```

This project replaces the Dreame phone app in that chain. It sends the same HTTPS requests the app would, using reverse-engineered authentication headers and API endpoints.

### Real cloud headers

Every request to the Dreame cloud requires:

| Header | Value |
|--------|-------|
| `Authorization` | `Basic ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg=` |
| `Tenant-Id` | `000000` |
| `Dreame-Meta` | `cv=i_829` |
| `Dreame-Rlc` | AES-ECB encrypted `region\|lang\|country` (key: `EETjszu*XI5znHsI`) |
| `Dreame-Auth` | `bearer <access_token>` |
| `User-Agent` | `Dreame_Smarthome/2.1.9 (iPhone; iOS 18.4.1; Scale/3.00)` |

## API endpoints

### POST `/dreame-auth/oauth/token`

**Email code login:**
```
grant_type=email
email=<email>
scope=all
platform=IOS
country=GB
lang=en

+ headers: Sms-Key, Sms-Code
```

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

### POST `/dreame-user-iot/iotuserbind/device/listV2`

Returns all devices bound to your account.

### POST `/dreame-iot-com-10000/device/sendCommand`

Send RPC commands. Supports `get_properties`, `set_properties`, and `action`.

**Example — start cleaning:**

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

### POST `/dreame-iot-com-10000/device/properties`

Batch property get/set.

## Properties reference

All properties are addressed by `(siid, piid)`. See `src/dreame_mocker/const.py` for code definitions.

### Device state & battery

| Property | SIID | PIID | Values |
|----------|------|------|--------|
| State | 2 | 1 | 1=Sweeping, 2=Idle, 3=Paused, 4=Error, 5=Returning, 6=Charging, 7=Mopping, 8=Drying, 9=Washing, 12=Sweep+Mop, 13=Charge Complete |
| Error | 2 | 2 | 0 = no error |
| Battery level | 3 | 1 | 0-100 |
| Charging status | 3 | 2 | true/false |

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

### Audio & other

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

## Local mock server

For offline development, run the built-in mock server which simulates the Dreame cloud API locally:

```bash
uv run dreame-mocker --log-level DEBUG
```

This starts:
- HTTP API on `:13267` (same endpoints as the real cloud)
- MQTT-style TCP status relay on `:19973` (pushes property changes)

The mock includes a full device state machine — cleaning cycles, battery drain/charge, dock return, etc. Point your `.env` at `localhost` to use it:

```bash
DREAME_HOST=localhost
DREAME_PORT=13267
```

### Mock server CLI flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--host` | string | `0.0.0.0` | Bind address |
| `--port` | int | `13267` | HTTP API port |
| `--mqtt-port` | int | `19973` | MQTT status relay port |
| `--device-name` | string | `X50 Ultra Complete` | Virtual device display name |
| `--device-model` | string | `dreame.vacuum.r2532a` | Model identifier |
| `--device-id` | string | auto-generated | Device ID |
| `--log-level` | choice | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

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
uv run pyright                        # type check (strict mode)
uv run dreame-mocker --log-level DEBUG  # run mock server
uv run python test_client.py          # test against real cloud
```

## Project structure

```
test_client.py              # real-cloud test client (mocks the phone app)
src/dreame_mocker/
  __init__.py               # package metadata
  const.py                  # SIID/PIID/AIID mappings, enums, API paths
  models.py                 # Pydantic request/response models
  state.py                  # device state machine and registry
  auth.py                   # OAuth2 mock token store
  server.py                 # FastAPI mock server (all 4 endpoints)
  mqtt.py                   # TCP status relay
  cli.py                    # mock server CLI entry point
```
