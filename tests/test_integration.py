import asyncio
import json
import shutil
import time

import pytest
import websockets

from ce_agent.auth import generate_token
from ce_agent.server import AgentServer


async def send(websocket, message):
    await websocket.send(json.dumps(message))


async def receive_until(websocket, message_type, contains=None):
    while True:
        message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=5))
        assert message["type"] != "error", message
        if message["type"] == message_type and (
            contains is None or contains in message.get("data", "")
        ):
            return message


async def authenticate(websocket, server):
    ts = int(time.time())
    await send(
        websocket,
        {"type": "auth", "token": generate_token(server.secret, ts), "ts": ts},
    )
    assert (await receive_until(websocket, "authenticated"))["version"] == "0.1.0"


def test_tmux_output_reconnect_replay_and_kill(tmp_path):
    if shutil.which("tmux") is None:
        pytest.skip("tmux is not installed")

    async def scenario():
        server = AgentServer(tmp_path, port=0)
        session_id = None
        try:
            await server.start()
        except PermissionError as exc:
            pytest.skip("sandbox does not permit local TCP listeners: {}".format(exc))
        url = "ws://127.0.0.1:{}".format(server.bound_port)
        try:
            async with websockets.connect(url, proxy=None) as websocket:
                await authenticate(websocket, server)
                await send(
                    websocket,
                    {"type": "create_session", "name": "integration", "command": "bash"},
                )
                created = await receive_until(websocket, "session_created")
                session_id = created["session"]["id"]
                await send(
                    websocket,
                    {"type": "attach_session", "id": session_id, "scrollback": 0},
                )
                await receive_until(websocket, "attached")
                await send(
                    websocket,
                    {
                        "type": "input",
                        "session_id": session_id,
                        "data": "echo hello-from-code-explorer\n",
                    },
                )
                output = await receive_until(
                    websocket, "output", "hello-from-code-explorer"
                )
                await send(
                    websocket, {"type": "detach", "session_id": session_id}
                )
                await receive_until(websocket, "detached")

            async with websockets.connect(url, proxy=None) as websocket:
                await authenticate(websocket, server)
                await send(
                    websocket,
                    {
                        "type": "attach_session",
                        "id": session_id,
                        "scrollback": output["seq"] - 1,
                    },
                )
                await receive_until(websocket, "attached")
                replay = await receive_until(
                    websocket, "output", "hello-from-code-explorer"
                )
                assert replay["seq"] == output["seq"]
                assert replay["replay"] is True
                await send(websocket, {"type": "kill_session", "id": session_id})
                await receive_until(websocket, "session_killed")
                assert not server.tmux.exists(session_id)
                session_id = None
        finally:
            if session_id is not None:
                server.tmux.kill(session_id)
            await server.stop()

    asyncio.run(scenario())
