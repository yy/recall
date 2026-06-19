import recall


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
                'sleep 45; current=$(pbpaste); if [ "$current" = "$(cat)" ]; then printf "" | pbcopy; fi',
            ],
            recall.subprocess.PIPE,
            True,
        )
    ]
    assert proc.stdin.written == b"secret-value"
    assert proc.stdin.closed is True
