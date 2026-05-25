import asyncio
import io
import json
import sys
import time
from contextlib import redirect_stdout
from unittest.mock import patch

import websockets

from ce_agent.auth import generate_token
from ce_agent.cli import main
from ce_agent.server import AgentServer


async def send(websocket, message):
    await websocket.send(json.dumps(message))


async def receive_until(websocket, message_type):
    while True:
        message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=5))
        assert message["type"] != "error", message
        if message["type"] == message_type:
            return message


async def authenticate(websocket, server):
    ts = int(time.time())
    await send(websocket, {"type": "auth", "token": generate_token(server.secret, ts), "ts": ts})
    await receive_until(websocket, "authenticated")


def run_cli(args):
    output = io.StringIO()
    with patch.object(sys, "argv", ["ce-agent", *args]), redirect_stdout(output):
        main()
    return output.getvalue().strip()


def test_token_json_emits_auth_message(tmp_path):
    payload = json.loads(run_cli(["token", "--data-dir", str(tmp_path), "--ts", "1234", "--json"]))

    assert payload == {
        "type": "auth",
        "token": generate_token((tmp_path / "agent.secret").read_bytes().strip(), 1234),
        "ts": 1234,
    }


def test_legacy_token_output_stays_without_type(tmp_path):
    payload = json.loads(run_cli(["token", "--data-dir", str(tmp_path), "--ts", "1234"]))

    assert payload == {
        "token": generate_token((tmp_path / "agent.secret").read_bytes().strip(), 1234),
        "ts": 1234,
    }


def test_list_sessions_uses_canonical_contract_fields(tmp_path):
    async def scenario():
        server = AgentServer(tmp_path, port=0)
        try:
            await server.start()
            url = "ws://127.0.0.1:{}".format(server.bound_port)
            async with websockets.connect(url, proxy=None) as websocket:
                await authenticate(websocket, server)
                server.store.create_session("sess_test", "Test", "zsh")
                await send(websocket, {"type": "list_sessions"})
                message = await receive_until(websocket, "sessions")
        finally:
            await server.stop()
        return message

    message = asyncio.run(scenario())

    assert message["sessions"] == [
        {
            "id": "sess_test",
            "name": "Test",
            "command": "zsh",
            "status": "stopped",
            "created_at": message["sessions"][0]["created_at"],
            "updated_at": message["sessions"][0]["updated_at"],
            "attached": False,
        }
    ]
    assert "created" not in message["sessions"][0]
    assert "last_active" not in message["sessions"][0]


def test_kill_session_uses_id_field_and_no_extra_ended_for_requester(tmp_path):
    async def scenario():
        server = AgentServer(tmp_path, port=0)
        try:
            await server.start()
            url = "ws://127.0.0.1:{}".format(server.bound_port)
            async with websockets.connect(url, proxy=None) as websocket:
                await authenticate(websocket, server)
                server.store.create_session("sess_test", "Test", "zsh")
                with patch.object(server.tmux, "exists", return_value=True), patch.object(server.tmux, "kill"):
                    await send(websocket, {"type": "kill_session", "id": "sess_test"})
                    return await receive_until(websocket, "session_killed")
        finally:
            await server.stop()

    assert asyncio.run(scenario()) == {"type": "session_killed", "id": "sess_test"}
