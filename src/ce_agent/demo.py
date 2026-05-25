import argparse
import asyncio
import json
import time
from pathlib import Path

import websockets

from .auth import ensure_secret, generate_token
from .cli import default_data_dir


async def send(websocket, message: dict) -> None:
    await websocket.send(json.dumps(message))


async def receive_type(websocket, wanted: str) -> dict:
    while True:
        message = json.loads(await asyncio.wait_for(websocket.recv(), timeout=5))
        if message["type"] == "error":
            raise RuntimeError(message)
        if message["type"] == wanted:
            return message


async def authenticate(websocket, data_dir: Path) -> None:
    ts = int(time.time())
    token = generate_token(ensure_secret(data_dir), ts)
    await send(websocket, {"type": "auth", "token": token, "ts": ts})
    await receive_type(websocket, "authenticated")


async def run_demo(url: str, data_dir: Path) -> None:
    async with websockets.connect(url, proxy=None) as websocket:
        await authenticate(websocket, data_dir)
        await send(websocket, {"type": "create_session", "name": "demo", "command": "bash"})
        session_id = (await receive_type(websocket, "session_created"))["session"]["id"]
        await send(websocket, {"type": "attach_session", "id": session_id, "scrollback": 0})
        await receive_type(websocket, "attached")
        await send(
            websocket,
            {"type": "input", "session_id": session_id, "data": "echo hello-from-code-explorer\n"},
        )
        output = await receive_type(websocket, "output")
        while "hello-from-code-explorer" not in output["data"]:
            output = await receive_type(websocket, "output")
        last_seq = output["seq"] - 1
        await send(websocket, {"type": "detach", "session_id": session_id})
        await receive_type(websocket, "detached")
    async with websockets.connect(url, proxy=None) as websocket:
        await authenticate(websocket, data_dir)
        await send(
            websocket,
            {"type": "attach_session", "id": session_id, "scrollback": last_seq},
        )
        await receive_type(websocket, "attached")
        replay = await receive_type(websocket, "output")
        if not replay.get("replay") or "hello-from-code-explorer" not in replay["data"]:
            raise RuntimeError("expected replayed echo output")
        await send(websocket, {"type": "kill_session", "id": session_id})
        await receive_type(websocket, "session_killed")
    print("demo passed: output replayed with seq={}".format(replay["seq"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Exercise a running ce-agent daemon")
    parser.add_argument("--url", default="ws://127.0.0.1:7681")
    parser.add_argument("--data-dir", default=default_data_dir(), type=Path)
    args = parser.parse_args()
    asyncio.run(run_demo(args.url, args.data_dir))


if __name__ == "__main__":
    main()

