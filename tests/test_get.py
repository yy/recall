import argparse

import recall


def test_get_secret_uses_1password_hint_by_default(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        recall,
        "load_data",
        lambda cfg: {
            "github": {
                "token": {
                    "kind": "secret",
                    "ref": "op://Private/GitHub/token",
                }
            }
        },
    )

    status = recall.cmd_get(argparse.Namespace(key="github.token", show=False), {})

    assert status == 0
    assert capsys.readouterr().out == (
        "github.token is a secret → op://Private/GitHub/token\n"
        "  run: recall secret github.token   (opens it in 1Password to copy by hand)\n"
    )


def test_get_secret_uses_keychain_copy_hint(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        recall,
        "load_data",
        lambda cfg: {
            "github": {
                "token": {
                    "kind": "secret",
                    "backend": "keychain",
                    "ref": "github-token",
                }
            }
        },
    )

    status = recall.cmd_get(argparse.Namespace(key="github.token", show=False), {})

    assert status == 0
    assert capsys.readouterr().out == (
        "github.token is a secret → github-token\n"
        "  run: recall secret github.token --copy   (resolves it via Keychain and copies it)\n"
    )


def test_get_file_show_resolves_relative_path_against_data_file(
    tmp_path, monkeypatch, capsys
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

    audit_calls = []

    def fake_audit(command: str, key: str) -> None:
        audit_calls.append((command, key))

    monkeypatch.setattr(recall, "audit", fake_audit)

    status = recall.cmd_get(
        argparse.Namespace(key="email.reply-template", show=True),
        {"data_file": "private/data.jsonl"},
    )

    assert status == 0
    assert capsys.readouterr().out == (
        str(recall_dir / "private" / "snippets" / "reply.md") + "\n"
    )
    assert audit_calls == [("get", "email.reply-template")]


def test_main_bare_namespace_lists_children_without_auditing(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(recall, "load_config", lambda: {})
    monkeypatch.setattr(
        recall,
        "load_data",
        lambda cfg: {
            "insurance": {
                "member-id": {
                    "kind": "account",
                    "value": "MEMBER-ID-EXAMPLE",
                    "note": "Health insurance member ID",
                },
                "portal": {
                    "kind": "url",
                    "value": "https://example.com/login",
                    "note": "Claims portal",
                },
            }
        },
    )

    audit_calls = []

    def fake_audit(command: str, key: str) -> None:
        audit_calls.append((command, key))

    monkeypatch.setattr(recall, "audit", fake_audit)

    status = recall.main(["insurance"])

    assert status == 0
    assert capsys.readouterr().out == (
        "insurance/  (namespace)\n"
        "  insurance.member-id  [account]  — Health insurance member ID\n"
        "  insurance.portal  [url]  — Claims portal\n"
    )
    assert audit_calls == []
