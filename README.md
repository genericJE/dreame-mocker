# dreame-mocker

Mock server for the Dreame vacuum cloud API. Simulates a **Dreame X50 Ultra Complete** so you can develop and test Home Assistant automations without hitting the real cloud.

## What it does

- **OAuth2 token endpoint** — accepts any credentials, issues mock tokens
- **Device list** — returns a virtual X50 Ultra Complete with configurable DID/model
- **RPC command handler** — supports `get_properties`, `set_properties`, and `action` calls using real SIID/PIID/AIID mappings
- **Device state machine** — simulates cleaning cycles, battery drain/charge, dock return, washing, drying, auto-empty
- **MQTT-style status relay** — pushes property changes to connected clients over TCP (length-prefixed JSON frames)

## Quick start

```bash
# install
uv sync

# run (defaults: HTTP on :13267, MQTT relay on :19973)
uv run dreame-mocker

# or with options
uv run dreame-mocker --port 13267 --mqtt-port 19973 --device-name "My Vacuum" --log-level DEBUG
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/dreame-auth/oauth/token` | OAuth2 password/refresh grant |
| POST | `/dreame-user-iot/iotuserbind/device/listV2` | List bound devices |
| POST | `/dreame-iot-com-10000/device/sendCommand` | Send RPC command to device |
| POST | `/dreame-iot-com-10000/device/properties` | Batch property get/set |

## Example: authenticate and start cleaning

```bash
# get a token
TOKEN=$(curl -s -X POST http://localhost:13267/dreame-auth/oauth/token \
  -d "grant_type=password&username=test@example.com&password=test" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# list devices
curl -s -X POST http://localhost:13267/dreame-user-iot/iotuserbind/device/listV2 \
  -H "Authorization: Bearer $TOKEN"

# start cleaning (action siid=2, aiid=1)
DID="<did from device list>"
curl -s -X POST http://localhost:13267/dreame-iot-com-10000/device/sendCommand \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"did\":\"$DID\",\"id\":1,\"data\":{\"did\":\"$DID\",\"id\":1,\"method\":\"action\",\"params\":{\"siid\":2,\"aiid\":1}}}"
```

## Configuration

All options via CLI flags:

```
--host           Bind address (default: 0.0.0.0)
--port           HTTP API port (default: 13267)
--mqtt-port      MQTT relay port (default: 19973)
--device-name    Virtual device name (default: X50 Ultra Complete)
--device-model   Model identifier (default: dreame.vacuum.r2532a)
--device-id      Device ID (auto-generated if omitted)
--log-level      DEBUG | INFO | WARNING | ERROR
```

## Supported SIID/PIID properties

See `src/dreame_mocker/const.py` for the full mapping. Key properties:

- **State** (2,1) — idle, sweeping, mopping, charging, etc.
- **Battery** (3,1) — 0-100
- **Suction level** (4,4) — quiet/standard/strong/turbo
- **Water volume** (4,5) — low/medium/high
- **Cleaning mode** (4,23) — sweep/mop/sweep+mop

## Supported actions

- Start (2,1), Pause (2,2), Return to dock (3,1), Stop (4,2)
- Start custom clean (4,1), Start washing (4,4), Start drying (4,5)
- Auto-empty dustbin (15,1)
