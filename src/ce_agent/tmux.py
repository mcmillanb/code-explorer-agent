import shlex
import subprocess
import uuid
from pathlib import Path


class TmuxError(RuntimeError):
    pass


class TmuxBackend:
    def __init__(self, raw_dir: Path):
        self.raw_dir = Path(raw_dir)

    @staticmethod
    def tmux_name(session_id: str) -> str:
        return "ce-" + session_id

    @staticmethod
    def new_session_id() -> str:
        return "sess_" + uuid.uuid4().hex[:12]

    def _run(self, args, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["tmux"] + list(args), capture_output=True, text=True, check=False
        )
        if check and result.returncode:
            raise TmuxError(result.stderr.strip() or "tmux command failed")
        return result

    def exists(self, session_id: str) -> bool:
        result = self._run(
            ["has-session", "-t", self.tmux_name(session_id)], check=False
        )
        return result.returncode == 0

    def create(self, session_id: str, command: str, cols: int = 120, rows: int = 40) -> None:
        if not command or not command.strip():
            raise ValueError("command must not be empty")
        self._run(
            [
                "new-session",
                "-d",
                "-s",
                self.tmux_name(session_id),
                "-x",
                str(cols),
                "-y",
                str(rows),
                "/bin/sh",
            ]
        )
        self.ensure_capture(session_id)
        launch_command = "exec /bin/sh -lc " + shlex.quote(command)
        self.send_input(session_id, launch_command)
        self._run(["send-keys", "-t", self.tmux_name(session_id) + ":0.0", "Enter"])

    def ensure_capture(self, session_id: str) -> None:
        raw_path = self.raw_dir / (session_id + ".stream")
        raw_path.touch(exist_ok=True)
        pipe_command = "cat >> " + shlex.quote(str(raw_path))
        self._run(
            ["pipe-pane", "-O", "-t", self.tmux_name(session_id) + ":0.0", pipe_command]
        )

    def send_input(self, session_id: str, data: str) -> None:
        self._run(
            ["send-keys", "-t", self.tmux_name(session_id) + ":0.0", "-l", data]
        )

    def resize(self, session_id: str, cols: int, rows: int) -> None:
        self._run(
            [
                "resize-window",
                "-t",
                self.tmux_name(session_id) + ":0",
                "-x",
                str(cols),
                "-y",
                str(rows),
            ]
        )

    def kill(self, session_id: str) -> None:
        self._run(["kill-session", "-t", self.tmux_name(session_id)], check=False)
