import subprocess

import pytest

import recall


def test_to_clipboard_reports_pbcopy_failure(monkeypatch) -> None:
    monkeypatch.setattr(recall.shutil, "which", lambda cmd: "/usr/bin/pbcopy")

    def fake_run(args, *, input=None, check=False, **kwargs):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(recall.subprocess, "run", fake_run)

    with pytest.raises(SystemExit, match="failed to copy to clipboard: pbcopy exited 1"):
        recall.to_clipboard("secret-value")


def test_to_clipboard_closes_background_pipe_for_delayed_clear(monkeypatch) -> None:
    monkeypatch.setattr(recall.shutil, "which", lambda cmd: "/usr/bin/pbcopy")

    run_calls = []

    def fake_run(args, *, input=None, check=False, **kwargs):
        run_calls.append((args, input, check))
        return None

    class FakeStdin:
        def __init__(self) -> None:
            self.written = b""
            self.closed = False

        def write(self, data: bytes) -> int:
            self.written += data
            return len(data)

        def close(self) -> None:
            self.closed = True

    class FakeProc:
        def __init__(self) -> None:
            self.stdin = FakeStdin()

    popen_calls = []
    proc = FakeProc()

    def fake_popen(args, *, stdin=None, start_new_session=False, **kwargs):
        popen_calls.append((args, stdin, start_new_session))
        return proc

    monkeypatch.setattr(recall.subprocess, "run", fake_run)
    monkeypatch.setattr(recall.subprocess, "Popen", fake_popen)

    recall.to_clipboard("secret-value", clear_after=45)

    assert run_calls == [(["pbcopy"], b"secret-value", True)]
    assert popen_calls == [
        (
            [
                "sh",
                "-c",
                'expected=$(cat); sleep 45; current=$(pbpaste); if [ "$current" = "$expected" ]; then printf "" | pbcopy; fi',
            ],
            recall.subprocess.PIPE,
            True,
        )
    ]
    assert proc.stdin.written == b"secret-value"
    assert proc.stdin.closed is True
