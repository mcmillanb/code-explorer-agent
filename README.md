# ce-agent prototype

`ce-agent` is a local WebSocket daemon that keeps terminal sessions alive in
tmux and persists sequenced output for reconnection replay. It binds only to
`127.0.0.1` by default and is intended to be reached through an SSH tunnel.

## Setup

Requirements are Python 3.9+, tmux, and the Python dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e . pytest
```

## Run

Start a daemon using the default `~/.code-explorer` data directory:

```bash
ce-agent daemon
```

For development or tests, the bind address, port, and data directory are
injectable:

```bash
ce-agent daemon --host 127.0.0.1 --port 7681 --data-dir /tmp/ce-agent-data
```

Generate an authentication message payload using the same data directory:

```bash
ce-agent token --data-dir /tmp/ce-agent-data
```

For clients that want to send the token output directly as the first
WebSocket message, use the canonical JSON auth form:

```bash
ce-agent token --data-dir /tmp/ce-agent-data --json
```

The secret is generated on first use as `agent.secret` with mode `0600`.
Tokens are `HMAC_SHA256(secret, str(ts))` values accepted within five minutes
of the supplied Unix timestamp.

## Protocol

The first WebSocket JSON message must be:

```json
{"type":"auth","token":"...","ts":1779710400}
```

After an `authenticated` reply, supported request types are
`list_sessions`, `create_session`, `attach_session`, `input`, `resize`,
`detach`, and `kill_session`. Each tmux session is named `ce-<session_id>`.

`list_sessions` replies with the canonical client contract shape:

```json
{"type":"sessions","sessions":[{"id":"sess_abc123","name":"zsh","command":"zsh","created_at":"...","updated_at":"...","status":"running","attached":false}]}
```

`kill_session` replies with:

```json
{"type":"session_killed","id":"sess_abc123"}
```

`attach_session` uses `scrollback` as the last output sequence already
received by the client:

```json
{"type":"attach_session","id":"sess_abc123","scrollback":41}
```

The daemon replays output events with `seq > 41`, preserving their original
sequence numbers and adding `"replay":true`. New output events continue with
monotonically increasing numbers and are stored in
`~/.code-explorer/logs/<session_id>.jsonl`.

## Demo

With a daemon running, this creates a bash session, sends an echo command,
disconnects, verifies replay after reconnection, and kills the session:

```bash
ce-agent-demo --data-dir ~/.code-explorer
```

## Tests

```bash
python3 -m pytest
```

The integration test launches the server on an ephemeral local port and uses
a real tmux-backed bash session. It is skipped in execution sandboxes that
prohibit opening even a localhost listener.

## Prototype Limitations

- Only sessions created by this daemon are tracked; attaching arbitrary
  pre-existing tmux sessions is not supported.
- Raw tmux pipe output is retained internally under `raw/` while JSONL logs
  are the protocol replay record; log rotation is not implemented.
- The prototype assumes one daemon process owns a data directory.
- There is no installer, service registration, TLS endpoint, or mobile client.
