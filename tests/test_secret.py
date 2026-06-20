import argparse

import pytest

import recall


@pytest.mark.parametrize(
    ("clear_seconds", "expected_message"),
    [
        (45, "copied github.token to clipboard (clears in 45s)"),
        (0, "copied github.token to clipboard (auto-clear disabled)"),
    ],
)
def test_secret_copy_reports_clipboard_clear_behavior(
    clear_seconds, expected_message, monkeypatch, capsys
) -> None:
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
    monkeypatch.setattr(recall, "vault_read", lambda entry, cfg: "secret-value")
    audit_calls = []

    def fake_audit(command: str, key: str) -> None:
        audit_calls.append((command, key))

    monkeypatch.setattr(recall, "audit", fake_audit)

    clipboard_calls = []

    def fake_to_clipboard(text: str, clear_after: int | None = None) -> None:
        clipboard_calls.append((text, clear_after))

    monkeypatch.setattr(recall, "to_clipboard", fake_to_clipboard)

    status = recall.cmd_secret(
        argparse.Namespace(key="github.token", copy=True),
        {"clipboard_clear_seconds": clear_seconds},
    )

    assert status == 0
    assert audit_calls == [("secret-copy", "github.token")]
    assert clipboard_calls == [("secret-value", clear_seconds)]
    assert expected_message in capsys.readouterr().out


def test_secret_rejects_show_option() -> None:
    parser = recall.build_parser()

    with pytest.raises(SystemExit, match="2"):
        parser.parse_args(["secret", "github.token", "--show"])


def test_secret_copy_does_not_audit_failed_clipboard_copy(monkeypatch) -> None:
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
    monkeypatch.setattr(recall, "vault_read", lambda entry, cfg: "secret-value")

    audit_calls = []

    def fake_audit(command: str, key: str) -> None:
        audit_calls.append((command, key))

    def fake_to_clipboard(text: str, clear_after: int | None = None) -> None:
        raise RuntimeError("clipboard unavailable")

    monkeypatch.setattr(recall, "audit", fake_audit)
    monkeypatch.setattr(recall, "to_clipboard", fake_to_clipboard)

    with pytest.raises(RuntimeError, match="clipboard unavailable"):
        recall.cmd_secret(
            argparse.Namespace(key="github.token", copy=True),
            {"clipboard_clear_seconds": 45},
        )

    assert audit_calls == []


def test_secret_open_audits_only_after_success(monkeypatch) -> None:
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

    audit_calls = []

    def fake_audit(command: str, key: str) -> None:
        audit_calls.append((command, key))

    monkeypatch.setattr(recall, "audit", fake_audit)
    monkeypatch.setattr(recall, "open_in_vault", lambda entry, cfg, key: 0)

    status = recall.cmd_secret(
        argparse.Namespace(key="github.token", copy=False),
        {"clipboard_clear_seconds": 45},
    )

    assert status == 0
    assert audit_calls == [("secret-open", "github.token")]


def test_secret_open_does_not_audit_failed_open(monkeypatch) -> None:
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

    audit_calls = []

    def fake_audit(command: str, key: str) -> None:
        audit_calls.append((command, key))

    monkeypatch.setattr(recall, "audit", fake_audit)
    monkeypatch.setattr(recall, "open_in_vault", lambda entry, cfg, key: 1)

    status = recall.cmd_secret(
        argparse.Namespace(key="github.token", copy=False),
        {"clipboard_clear_seconds": 45},
    )

    assert status == 1
    assert audit_calls == []


def test_open_in_vault_reports_failure_when_opening_item_link_fails(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        recall,
        "onepassword_deeplink",
        lambda ref: "onepassword://view-item/?v=vault&i=item",
    )
    monkeypatch.setattr(
        recall.subprocess,
        "run",
        lambda args, check=False: argparse.Namespace(returncode=1),
    )

    status = recall.open_in_vault(
        {"kind": "secret", "ref": "op://Private/GitHub/token"},
        {"default_backend": "1password"},
        "github.token",
    )

    assert status == 1
    assert "failed to open 1Password item for 'github.token'" in capsys.readouterr().err


def test_open_in_vault_reports_failure_when_opening_app_fallback_fails(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(recall, "onepassword_deeplink", lambda ref: None)
    monkeypatch.setattr(
        recall.subprocess,
        "run",
        lambda args, check=False: argparse.Namespace(returncode=1),
    )

    status = recall.open_in_vault(
        {"kind": "secret", "ref": "op://Private/GitHub/token"},
        {"default_backend": "1password"},
        "github.token",
    )

    assert status == 1
    assert "failed to open 1Password" in capsys.readouterr().err


def test_open_in_vault_falls_back_to_app_when_deeplink_lookup_times_out(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(recall.shutil, "which", lambda cmd: "/usr/bin/op")

    def fake_run(args, **kwargs):
        if args[:3] == ["op", "item", "get"]:
            assert kwargs["timeout"] == recall.ONEPASSWORD_METADATA_TIMEOUT_SECONDS
            raise recall.subprocess.TimeoutExpired(
                cmd=args, timeout=recall.ONEPASSWORD_METADATA_TIMEOUT_SECONDS
            )
        if args == ["open", "onepassword://"]:
            return argparse.Namespace(returncode=0)
        raise AssertionError(f"unexpected args: {args}")

    monkeypatch.setattr(recall.subprocess, "run", fake_run)

    status = recall.open_in_vault(
        {"kind": "secret", "ref": "op://Private/GitHub/token"},
        {"default_backend": "1password"},
        "github.token",
    )

    assert status == 0
    assert (
        "opened 1Password — find: op://Private/GitHub/token" in capsys.readouterr().out
    )


def test_onepassword_deeplink_returns_none_for_unexpected_op_metadata_shape(
    monkeypatch,
) -> None:
    monkeypatch.setattr(recall.shutil, "which", lambda cmd: "/usr/bin/op")

    def fake_run(args, **kwargs):
        if args[:3] == ["op", "item", "get"]:
            return argparse.Namespace(stdout='{"id":"item-uuid","vault":"Private"}')
        if args[:2] == ["op", "whoami"]:
            return argparse.Namespace(stdout='{"account_uuid":"account-uuid"}')
        raise AssertionError(f"unexpected args: {args}")

    monkeypatch.setattr(recall.subprocess, "run", fake_run)

    assert recall.onepassword_deeplink("op://Private/GitHub/token") is None


def test_onepassword_deeplink_falls_back_to_account_list_when_whoami_unavailable(
    monkeypatch,
) -> None:
    # Regression: with only the desktop-app integration enabled, `op whoami`
    # reports "not signed in" but `op account list` still answers. recall must
    # source the account id from the fallback so the deep link stays specific.
    monkeypatch.setattr(recall.shutil, "which", lambda cmd: "/usr/bin/op")

    def fake_run(args, **kwargs):
        if args[:3] == ["op", "item", "get"]:
            return argparse.Namespace(
                stdout='{"id":"item-uuid","vault":{"id":"vault-uuid"}}'
            )
        if args[:2] == ["op", "whoami"]:
            raise recall.subprocess.CalledProcessError(1, args, stderr="not signed in")
        if args[:3] == ["op", "account", "list"]:
            return argparse.Namespace(stdout='[{"account_uuid":"acct-uuid"}]')
        raise AssertionError(f"unexpected args: {args}")

    monkeypatch.setattr(recall.subprocess, "run", fake_run)

    assert (
        recall.onepassword_deeplink("op://Private/known-traveler-number-yy/notesPlain")
        == "onepassword://view-item/?v=vault-uuid&i=item-uuid&a=acct-uuid"
    )


def test_onepassword_deeplink_omits_account_when_unresolvable(monkeypatch) -> None:
    # Both whoami and account list fail: still return a usable v+i link, just
    # without the optional account disambiguator.
    monkeypatch.setattr(recall.shutil, "which", lambda cmd: "/usr/bin/op")

    def fake_run(args, **kwargs):
        if args[:3] == ["op", "item", "get"]:
            return argparse.Namespace(
                stdout='{"id":"item-uuid","vault":{"id":"vault-uuid"}}'
            )
        if args[:2] == ["op", "whoami"] or args[:3] == ["op", "account", "list"]:
            raise recall.subprocess.CalledProcessError(1, args, stderr="not signed in")
        raise AssertionError(f"unexpected args: {args}")

    monkeypatch.setattr(recall.subprocess, "run", fake_run)

    link = recall.onepassword_deeplink("op://Private/item/field")
    assert link == "onepassword://view-item/?v=vault-uuid&i=item-uuid"
    assert "&a=" not in link


def test_onepassword_deeplink_includes_account_when_signed_in(monkeypatch) -> None:
    monkeypatch.setattr(recall.shutil, "which", lambda cmd: "/usr/bin/op")

    def fake_run(args, **kwargs):
        if args[:3] == ["op", "item", "get"]:
            return argparse.Namespace(
                stdout='{"id":"item-uuid","vault":{"id":"vault-uuid"}}'
            )
        if args[:2] == ["op", "whoami"]:
            return argparse.Namespace(stdout='{"account_uuid":"acct-uuid"}')
        raise AssertionError(f"unexpected args: {args}")

    monkeypatch.setattr(recall.subprocess, "run", fake_run)

    assert (
        recall.onepassword_deeplink("op://Private/item/field")
        == "onepassword://view-item/?v=vault-uuid&i=item-uuid&a=acct-uuid"
    )
