import argparse
import asyncio
import json
import time
from pathlib import Path

from .auth import ensure_secret, generate_token
from .server import AgentServer


def default_data_dir() -> Path:
    return Path.home() / ".code-explorer"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Code Explorer persistent session agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    daemon = subparsers.add_parser("daemon", help="run the WebSocket daemon")
    daemon.add_argument("--host", default="127.0.0.1")
    daemon.add_argument("--port", default=7681, type=int)
    daemon.add_argument("--data-dir", default=default_data_dir(), type=Path)
    token = subparsers.add_parser("token", help="generate a short-lived authentication token")
    token.add_argument("--data-dir", default=default_data_dir(), type=Path)
    token.add_argument("--ts", type=int)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "token":
        timestamp = int(time.time()) if args.ts is None else args.ts
        secret = ensure_secret(args.data_dir)
        print(json.dumps({"token": generate_token(secret, timestamp), "ts": timestamp}))
        return
    server = AgentServer(args.data_dir, args.host, args.port)
    try:
        asyncio.run(server.serve_forever())
    except KeyboardInterrupt:
        pass

