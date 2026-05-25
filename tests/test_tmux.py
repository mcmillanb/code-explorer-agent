from unittest.mock import patch

from ce_agent.tmux import TmuxBackend


def test_create_installs_capture_before_launching_full_shell_command(tmp_path):
    backend = TmuxBackend(tmp_path)

    with patch("ce_agent.tmux.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stderr = ""
        backend.create("sess_test", "echo one; echo two")

    args = [call.args[0] for call in run.call_args_list]
    assert args[0][-1] == "/bin/sh"
    assert args[1][1] == "pipe-pane"
    assert args[2][-1] == "exec /bin/sh -lc 'echo one; echo two'"
    assert args[3][-1] == "Enter"

