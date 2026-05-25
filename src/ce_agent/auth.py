import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path
from typing import Optional


MAX_SKEW_SECONDS = 300


def ensure_secret(data_dir: Path) -> bytes:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "agent.secret"
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_bytes().strip()
    secret = secrets.token_bytes(32)
    with os.fdopen(fd, "wb") as handle:
        handle.write(secret.hex().encode("ascii") + b"\n")
    os.chmod(str(path), 0o600)
    return secret.hex().encode("ascii")


def generate_token(secret: bytes, ts: int) -> str:
    return hmac.new(secret, str(int(ts)).encode("ascii"), hashlib.sha256).hexdigest()


def verify_token(
    secret: bytes,
    token: str,
    ts: object,
    now: Optional[int] = None,
    max_skew: int = MAX_SKEW_SECONDS,
) -> bool:
    if isinstance(ts, bool):
        return False
    try:
        timestamp = int(ts)
    except (TypeError, ValueError):
        return False
    current = int(time.time()) if now is None else int(now)
    if abs(current - timestamp) > max_skew:
        return False
    expected = generate_token(secret, timestamp)
    return hmac.compare_digest(expected, str(token))

