# Claude Code Instructions

## Forbidden files

- **NEVER read, display, or access `.env`** — it contains user credentials. Do not use the Read tool, Bash cat/head/tail, or any other method to view its contents.

## Project context

- This is a Python project managed with `uv`
- Type checking uses `pyright` in strict mode (see `pyrightconfig.json`)
- This project mocks the **Dreame mobile app** (not the cloud server) — it acts as a client that talks to the real Dreame cloud API to control a Dreame X50 Ultra Complete robot vacuum
- The project also includes a local mock server for offline development/testing
- Run the mock server with `uv run dreame-mocker`
- Run the real-cloud test client with `uv run python test_client.py`
- Run type checks with `uv run pyright`
