import argparse

import recall


def test_format_canonicalizes_fields_but_preserves_order(monkeypatch, capsys) -> None:
    # `format` rewrites whitespace and field order within each record, but keeps
    # the entries in the file's own (tree-insertion) order — it does not re-sort.
    monkeypatch.setattr(
        recall,
        "load_data",
        lambda cfg: {
            "orcid": {
                "self": {
                    "note": "My ORCID iD",
                    "value": "0000-0000-0000-0000",
                    "kind": "id",
                }
            },
            "github": {
                "token": {
                    "ref": "op://Private/GitHub/token",
                    "backend": "1password",
                    "kind": "secret",
                    "extra": "kept",
                }
            },
        },
    )

    status = recall.cmd_format(argparse.Namespace(check=False), {})

    assert status == 0
    assert capsys.readouterr().out == (
        '{"key": "orcid.self", "kind": "id", "value": "0000-0000-0000-0000", '
        '"note": "My ORCID iD"}\n'
        '{"key": "github.token", "kind": "secret", "backend": "1password", '
        '"ref": "op://Private/GitHub/token", "extra": "kept"}\n'
    )


def test_format_check_succeeds_for_canonical_data(
    tmp_path, monkeypatch, capsys
) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    canonical = '{"key": "orcid.self", "kind": "id", "value": "0000-0000-0000-0000"}\n'
    (recall_dir / "config.json").write_text(
        '{"data_file":"data.jsonl","clipboard_clear_seconds":45,"default_backend":"1password"}\n'
    )
    (recall_dir / "data.jsonl").write_text(canonical)
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    status = recall.main(["format", "--check"])

    assert status == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_format_check_reports_noncanonical_data(tmp_path, monkeypatch, capsys) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "config.json").write_text(
        '{"data_file":"data.jsonl","clipboard_clear_seconds":45,"default_backend":"1password"}\n'
    )
    (recall_dir / "data.jsonl").write_text(
        '{"value":"0000-0000-0000-0000","kind":"id","key":"orcid.self"}\n'
    )
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    status = recall.main(["format", "--check"])

    assert status == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert (
        captured.err
        == f"recall: data file is not in canonical format: {recall_dir / 'data.jsonl'}\n"
    )
