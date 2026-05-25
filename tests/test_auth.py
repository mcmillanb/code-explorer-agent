import stat

from ce_agent.auth import ensure_secret, generate_token, verify_token


def test_secret_created_with_private_mode_and_token_verifies(tmp_path):
    secret = ensure_secret(tmp_path)
    mode = stat.S_IMODE((tmp_path / "agent.secret").stat().st_mode)
    token = generate_token(secret, 1000)

    assert mode == 0o600
    assert verify_token(secret, token, 1000, now=1200)
    assert not verify_token(secret, token, 1000, now=1301)
    assert not verify_token(secret, "incorrect", 1000, now=1000)


def test_secret_is_reused(tmp_path):
    assert ensure_secret(tmp_path) == ensure_secret(tmp_path)

