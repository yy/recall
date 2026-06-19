import argparse

import recall


def test_doctor_reports_keychain_without_irrelevant_op_warning(
    tmp_path, monkeypatch, capsys
) -> None:
    data_file = tmp_path / "data.jsonl"
    data_file.write_text("")
    monkeypatch.setattr(
        recall,
        "load_config_for_doctor",
        lambda: ({"default_backend": "keychain", "data_file": str(data_file)}, None),
    )
    monkeypatch.setattr(
        recall,
        "load_data",
        lambda cfg: {
            "github": {
                "token": {
                    "kind": "secret",
                    "ref": "github-token",
                }
            }
        },
    )
    monkeypatch.setattr(
        recall.shutil,
        "which",
        lambda cmd: "/usr/bin/security" if cmd == "security" else None,
    )

    status = recall.cmd_doctor(argparse.Namespace(), {})

    assert status == 0
    output = capsys.readouterr().out
    assert "security   : ✓ /usr/bin/security" in output
    assert "op CLI" not in output


def test_doctor_reports_entry_backends_in_addition_to_default_backend(
    tmp_path, monkeypatch, capsys
) -> None:
    data_file = tmp_path / "data.jsonl"
    data_file.write_text("")
    monkeypatch.setattr(
        recall,
        "load_config_for_doctor",
        lambda: ({"default_backend": "keychain", "data_file": str(data_file)}, None),
    )
    monkeypatch.setattr(
        recall,
        "load_data",
        lambda cfg: {
            "apple": {"id": {"kind": "secret", "ref": "apple-login"}},
            "github": {
                "token": {
                    "kind": "secret",
                    "backend": "1password",
                    "ref": "op://Private/GitHub/token",
                }
            },
        },
    )
    monkeypatch.setattr(
        recall.shutil,
        "which",
        lambda cmd: {
            "op": "/opt/homebrew/bin/op",
            "security": "/usr/bin/security",
        }.get(cmd),
    )

    status = recall.cmd_doctor(argparse.Namespace(), {})

    assert status == 0
    output = capsys.readouterr().out
    assert "security   : ✓ /usr/bin/security" in output
    assert "op CLI     : ✓ /opt/homebrew/bin/op" in output
