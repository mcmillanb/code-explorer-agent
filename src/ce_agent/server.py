import asyncio
import json
from pathlib import Path
from typing import Dict, Optional, Set

import websockets
from websockets.exceptions import ConnectionClosed

from . import __version__
from .auth import ensure_secret, verify_token
from .storage import Session, Store
from .tmux import TmuxBackend, TmuxError


class AgentServer:
    def __init__(self, data_dir: Path, host: str = "127.0.0.1", port: int = 7681):
        self.host = host
        self.port = port
        self.store = Store(Path(data_dir))
        self.secret = ensure_secret(Path(data_dir))
        self.tmux = TmuxBackend(self.store.raw_dir)
        self._server = None
        self._pumps: Dict[str, asyncio.Task] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._subscribers: Dict[str, Set[object]] = {}

    @property
    def bound_port(self) -> int:
        if self._server is None:
            return self.port
        return self._server.sockets[0].getsockname()[1]

    async def start(self) -> None:
        self._server = await websockets.serve(self._handle_connection, self.host, self.port)
        for session in self.store.list_sessions():
            if self.tmux.exists(session.id):
                self.tmux.ensure_capture(session.id)
                self._ensure_pump(session.id)

    async def stop(self) -> None:
        for task in list(self._pumps.values()):
            task.cancel()
        if self._pumps:
            await asyncio.gather(*self._pumps.values(), return_exceptions=True)
        self._pumps.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def serve_forever(self) -> None:
        await self.start()
        assert self._server is not None
        await self._server.serve_forever()

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    def _ensure_pump(self, session_id: str) -> None:
        task = self._pumps.get(session_id)
        if task is None or task.done():
            self._pumps[session_id] = asyncio.create_task(self._pump(session_id))

    async def _pump(self, session_id: str) -> None:
        try:
            while self.store.get_session(session_id) is not None:
                async with self._lock(session_id):
                    await self._import_raw_output(session_id)
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    async def _import_raw_output(self, session_id: str) -> None:
        session = self.store.get_session(session_id)
        if session is None:
            return
        path = self.store.raw_path(session_id)
        if not path.exists():
            return
        with path.open("rb") as handle:
            handle.seek(session.raw_offset)
            payload = handle.read()
            offset = handle.tell()
        if not payload:
            return
        event = self.store.append_output(
            session_id, payload.decode("utf-8", errors="replace")
        )
        self.store.set_raw_offset(session_id, offset)
        message = dict(event, session_id=session_id)
        await self._broadcast(session_id, message)

    async def _broadcast(self, session_id: str, message: dict) -> None:
        subscribers = self._subscribers.get(session_id, set()).copy()
        dead = []
        for websocket in subscribers:
            try:
                await self._send(websocket, message)
            except ConnectionClosed:
                dead.append(websocket)
        for websocket in dead:
            self._subscribers.get(session_id, set()).discard(websocket)

    async def _send(self, websocket, message: dict) -> None:
        await websocket.send(json.dumps(message, separators=(",", ":")))

    async def _error(self, websocket, code: str, message: str) -> None:
        await self._send(websocket, {"type": "error", "code": code, "message": message})

    async def _handle_connection(self, websocket) -> None:
        attached: Set[str] = set()
        try:
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=10)
                auth = json.loads(raw)
            except (asyncio.TimeoutError, json.JSONDecodeError, TypeError):
                await self._error(websocket, "auth_required", "First message must authenticate")
                return
            if auth.get("type") != "auth" or not verify_token(
                self.secret, auth.get("token", ""), auth.get("ts")
            ):
                await self._error(websocket, "auth_failed", "Invalid or expired token")
                return
            await self._send(websocket, {"type": "authenticated", "version": __version__})
            async for raw in websocket:
                try:
                    request = json.loads(raw)
                except json.JSONDecodeError:
                    await self._error(websocket, "invalid_json", "Message is not valid JSON")
                    continue
                await self._dispatch(websocket, request, attached)
        except ConnectionClosed:
            pass
        finally:
            for session_id in attached:
                self._subscribers.get(session_id, set()).discard(websocket)

    async def _dispatch(self, websocket, request: dict, attached: Set[str]) -> None:
        message_type = request.get("type")
        if message_type == "list_sessions":
            sessions = [self._session_json(s) for s in self.store.list_sessions()]
            await self._send(websocket, {"type": "session_list", "sessions": sessions})
        elif message_type == "create_session":
            await self._create_session(websocket, request)
        elif message_type == "attach_session":
            await self._attach_session(websocket, request, attached)
        elif message_type == "input":
            await self._input(websocket, request)
        elif message_type == "resize":
            await self._resize(websocket, request)
        elif message_type == "detach":
            session_id = str(request.get("session_id", ""))
            self._subscribers.get(session_id, set()).discard(websocket)
            attached.discard(session_id)
            await self._send(websocket, {"type": "detached", "session_id": session_id})
        elif message_type == "kill_session":
            await self._kill(websocket, str(request.get("id", "")), attached)
        else:
            await self._error(websocket, "unknown_type", "Unsupported message type")

    def _session_json(self, session: Session) -> dict:
        return {
            "id": session.id,
            "name": session.name,
            "command": session.command,
            "created": session.created,
            "last_active": session.last_active,
            "attached": bool(self._subscribers.get(session.id)),
        }

    def _lookup(self, session_id: str) -> Optional[Session]:
        return self.store.get_session(session_id)

    async def _create_session(self, websocket, request: dict) -> None:
        name = request.get("name")
        command = request.get("command")
        if not isinstance(name, str) or not name.strip() or not isinstance(command, str):
            await self._error(websocket, "invalid_request", "name and command are required")
            return
        session_id = self.tmux.new_session_id()
        try:
            self.tmux.create(session_id, command)
            session = self.store.create_session(session_id, name.strip(), command)
        except (TmuxError, ValueError) as exc:
            self.tmux.kill(session_id)
            await self._error(websocket, "create_failed", str(exc))
            return
        self._ensure_pump(session_id)
        await self._send(websocket, {"type": "session_created", "session": self._session_json(session)})

    async def _attach_session(self, websocket, request: dict, attached: Set[str]) -> None:
        session_id = str(request.get("id", ""))
        session = self._lookup(session_id)
        if session is None or not self.tmux.exists(session_id):
            await self._error(websocket, "session_not_found", "No running session with that ID")
            return
        try:
            after_seq = int(request.get("scrollback", 0))
        except (TypeError, ValueError):
            await self._error(websocket, "invalid_request", "scrollback must be a sequence number")
            return
        self._ensure_pump(session_id)
        async with self._lock(session_id):
            await self._import_raw_output(session_id)
            events = self.store.replay_after(session_id, max(0, after_seq))
            self._subscribers.setdefault(session_id, set()).add(websocket)
            attached.add(session_id)
            await self._send(websocket, {"type": "attached", "session_id": session_id})
            for event in events:
                await self._send(
                    websocket, dict(event, session_id=session_id, replay=True)
                )

    async def _input(self, websocket, request: dict) -> None:
        session_id = str(request.get("session_id", ""))
        data = request.get("data")
        if self._lookup(session_id) is None or not self.tmux.exists(session_id):
            await self._error(websocket, "session_not_found", "No running session with that ID")
            return
        if not isinstance(data, str):
            await self._error(websocket, "invalid_request", "data must be a string")
            return
        try:
            self.tmux.send_input(session_id, data)
            self.store.touch(session_id)
        except TmuxError as exc:
            await self._error(websocket, "input_failed", str(exc))

    async def _resize(self, websocket, request: dict) -> None:
        session_id = str(request.get("session_id", ""))
        try:
            cols, rows = int(request["cols"]), int(request["rows"])
        except (KeyError, TypeError, ValueError):
            await self._error(websocket, "invalid_request", "cols and rows must be integers")
            return
        if self._lookup(session_id) is None or not self.tmux.exists(session_id):
            await self._error(websocket, "session_not_found", "No running session with that ID")
            return
        if cols < 1 or rows < 1:
            await self._error(websocket, "invalid_request", "cols and rows must be positive")
            return
        try:
            self.tmux.resize(session_id, cols, rows)
            await self._send(websocket, {"type": "resized", "session_id": session_id})
        except TmuxError as exc:
            await self._error(websocket, "resize_failed", str(exc))

    async def _kill(self, websocket, session_id: str, attached: Set[str]) -> None:
        if self._lookup(session_id) is None:
            await self._error(websocket, "session_not_found", "No session with that ID")
            return
        self.tmux.kill(session_id)
        self.store.delete_session(session_id)
        for client in self._subscribers.pop(session_id, set()).copy():
            await self._send(client, {"type": "session_ended", "session_id": session_id})
        attached.discard(session_id)
        await self._send(websocket, {"type": "session_killed", "session_id": session_id})

