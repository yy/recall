import argparse
from pathlib import Path

import recall


def test_open_file_expands_path_and_audits_on_success(monkeypatch) -> None:
    monkeypatch.setattr(
        recall,
        "load_data",
        lambda cfg: {
            "email": {
                "reply-template": {
                    "kind": "file",
                    "value": "~/git/dotfiles/recall/snippets/reply.md",
                }
            }
        },
    )

    run_calls = []
    audit_calls = []

    def fake_run(args, check=False):
        run_calls.append((args, check))
        return argparse.Namespace(returncode=0)

    def fake_audit(command: str, key: str) -> None:
        audit_calls.append((command, key))

    monkeypatch.setattr(recall.subprocess, "run", fake_run)
    monkeypatch.setattr(recall, "audit", fake_audit)

    status = recall.cmd_open(
        argparse.Namespace(key="email.reply-template"),
        {},
    )

    assert status == 0
    assert run_calls == [
        (["open", str(Path("~/git/dotfiles/recall/snippets/reply.md").expanduser())], False),
    ]
    assert audit_calls == [("open", "email.reply-template")]


def test_open_file_resolves_relative_path_against_data_file(
    tmp_path, monkeypatch
) -> None:
    recall_dir = tmp_path / "config"
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))
    monkeypatch.setattr(
        recall,
        "load_data",
        lambda cfg: {
            "email": {
                "reply-template": {
                    "kind": "file",
                    "value": "snippets/reply.md",
                }
            }
        },
    )

    run_calls = []
    audit_calls = []

    def fake_run(args, check=False):
        run_calls.append((args, check))
        return argparse.Namespace(returncode=0)

    def fake_audit(command: str, key: str) -> None:
        audit_calls.append((command, key))

    monkeypatch.setattr(recall.subprocess, "run", fake_run)
    monkeypatch.setattr(recall, "audit", fake_audit)

    status = recall.cmd_open(
        argparse.Namespace(key="email.reply-template"),
        {"data_file": "private/data.jsonl"},
    )

    assert status == 0
    assert run_calls == [
        (
            ["open", str(recall_dir / "private" / "snippets" / "reply.md")],
            False,
        ),
    ]
    assert audit_calls == [("open", "email.reply-template")]


def test_open_does_not_audit_failed_open(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        recall,
        "load_data",
        lambda cfg: {
            "insurance": {
                "portal": {
                    "kind": "url",
                    "value": "https://example.com/login",
                }
            }
        },
    )

    audit_calls = []

    def fake_audit(command: str, key: str) -> None:
        audit_calls.append((command, key))

    monkeypatch.setattr(recall, "audit", fake_audit)
    monkeypatch.setattr(
        recall.subprocess,
        "run",
        lambda args, check=False: argparse.Namespace(returncode=1),
    )

    status = recall.cmd_open(
        argparse.Namespace(key="insurance.portal"),
        {},
    )

    assert status == 1
    assert audit_calls == []
    assert "failed to open 'insurance.portal'" in capsys.readouterr().err


def test_open_reports_launch_oserror_without_auditing(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        recall,
        "load_data",
        lambda cfg: {
            "insurance": {
                "portal": {
                    "kind": "url",
                    "value": "https://example.com/login",
                }
            }
        },
    )

    audit_calls = []

    def fake_audit(command: str, key: str) -> None:
        audit_calls.append((command, key))

    def fake_run(args, check=False):
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(recall, "audit", fake_audit)
    monkeypatch.setattr(recall.subprocess, "run", fake_run)

    status = recall.cmd_open(
        argparse.Namespace(key="insurance.portal"),
        {},
    )

    assert status == 1
    assert audit_calls == []
    assert (
        "failed to open 'insurance.portal': No such file or directory"
        in capsys.readouterr().err
    )
