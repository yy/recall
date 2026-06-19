from pathlib import Path

import pytest

import recall


def test_jsonl_records_normalize_to_nested_tree() -> None:
    records = [
        {
            "key": "orcid.self",
            "kind": "id",
            "value": "0000-0000-0000-0000",
            "tags": ["identity"],
        },
        {
            "key": "insurance.portal",
            "kind": "url",
            "value": "https://example.com/login",
            "note": "Claims portal",
        },
        {
            "key": "github.token",
            "kind": "secret",
            "backend": "1password",
            "ref": "op://Private/GitHub/token",
        },
    ]

    tree = recall.normalize_data(records, Path("data.jsonl"))

    assert recall.resolve(tree, "orcid.self")["value"] == "0000-0000-0000-0000"
    assert recall.resolve(tree, "insurance.portal")["kind"] == "url"
    assert recall.resolve(tree, "github.token")["ref"] == "op://Private/GitHub/token"
    assert sorted(key for key, _ in recall.walk_entries(tree)) == [
        "github.token",
        "insurance.portal",
        "orcid.self",
    ]


def test_entry_and_namespace_conflict_exits() -> None:
    records = [
        {
            "key": "orcid",
            "kind": "id",
            "value": "0000-0000-0000-0000",
        },
        {
            "key": "orcid.self",
            "kind": "id",
            "value": "0000-0000-0000-0001",
        },
    ]

    with pytest.raises(SystemExit, match="conflicts with entry"):
        recall.normalize_data(records, Path("data.jsonl"))


def test_duplicate_entries_exit() -> None:
    records = [
        {
            "key": "orcid.self",
            "kind": "id",
            "value": "0000-0000-0000-0000",
        },
        {
            "key": "orcid.self",
            "kind": "id",
            "value": "0000-0000-0000-0001",
        },
    ]

    with pytest.raises(SystemExit, match="duplicate or conflicting entry"):
        recall.normalize_data(records, Path("data.jsonl"))


def test_missing_key_exits() -> None:
    records = [{"kind": "id", "value": "0000-0000-0000-0000"}]

    with pytest.raises(SystemExit, match="must have string field 'key'"):
        recall.normalize_data(records, Path("data.jsonl"))


def test_empty_key_segment_exits() -> None:
    records = [{"key": "orcid..self", "kind": "id", "value": "x"}]

    with pytest.raises(SystemExit, match="invalid empty key segment"):
        recall.normalize_data(records, Path("data.jsonl"))


def test_key_only_record_exits() -> None:
    records = [{"key": "orcid.self"}]

    with pytest.raises(SystemExit, match="must include 'kind', 'value', or 'ref'"):
        recall.normalize_data(records, Path("data.jsonl"))


def test_normalize_data_rejects_mismatched_line_number_count() -> None:
    records = [{"key": "orcid.self", "kind": "id", "value": "x"}]

    with pytest.raises(ValueError, match="line_numbers length must match records length"):
        recall.normalize_data(records, Path("data.jsonl"), line_numbers=[])


def test_non_secret_entry_without_kind_exits() -> None:
    records = [{"key": "orcid.self", "value": "0000-0000-0000-0000"}]

    with pytest.raises(SystemExit, match="field 'kind' must be a string"):
        recall.normalize_data(records, Path("data.jsonl"))


def test_secret_entry_without_kind_exits() -> None:
    records = [{"key": "github.token", "ref": "op://Private/GitHub/token"}]

    with pytest.raises(SystemExit, match="field 'kind' must be a string"):
        recall.normalize_data(records, Path("data.jsonl"))


def test_non_secret_entry_without_value_exits() -> None:
    records = [{"key": "orcid.self", "kind": "id"}]

    with pytest.raises(SystemExit, match="non-secret entries must include 'value'"):
        recall.normalize_data(records, Path("data.jsonl"))


def test_non_secret_entry_with_empty_value_exits() -> None:
    records = [{"key": "insurance.portal", "kind": "url", "value": ""}]

    with pytest.raises(SystemExit, match="non-secret entries must include 'value'"):
        recall.normalize_data(records, Path("data.jsonl"))


def test_non_secret_value_must_be_a_string() -> None:
    records = [{"key": "orcid.self", "kind": "id", "value": 12345}]

    with pytest.raises(SystemExit, match="field 'value' must be a string"):
        recall.normalize_data(records, Path("data.jsonl"))


def test_secret_entry_without_ref_exits() -> None:
    records = [{"key": "github.token", "kind": "secret"}]

    with pytest.raises(SystemExit, match="secret entries must include 'ref'"):
        recall.normalize_data(records, Path("data.jsonl"))


def test_secret_entry_with_unknown_backend_exits() -> None:
    records = [
        {
            "key": "github.token",
            "kind": "secret",
            "backend": "vaulty",
            "ref": "op://Private/GitHub/token",
        }
    ]

    with pytest.raises(
        SystemExit, match="field 'backend' must be one of: 1password, keychain, op"
    ):
        recall.normalize_data(records, Path("data.jsonl"))


def test_multiline_values_must_be_file_backed() -> None:
    records = [
        {
            "key": "email.signature",
            "kind": "snippet",
            "value": "Best,\nYY\n",
            "note": "Email signature",
        }
    ]

    with pytest.raises(SystemExit, match="must be one line"):
        recall.normalize_data(records, Path("data.jsonl"))


def test_tags_must_be_one_line_strings() -> None:
    records = [
        {
            "key": "email.signature",
            "kind": "file",
            "value": "~/git/dotfiles/recall/snippets/email-signature.txt",
            "tags": ["email", 1],
        }
    ]

    with pytest.raises(SystemExit, match="tags must be one-line strings"):
        recall.normalize_data(records, Path("data.jsonl"))


def test_secret_ref_must_be_a_string() -> None:
    records = [
        {
            "key": "github.token",
            "kind": "secret",
            "backend": "1password",
            "ref": 123,
        }
    ]

    with pytest.raises(SystemExit, match="field 'ref' must be a string"):
        recall.normalize_data(records, Path("data.jsonl"))


def test_file_entries_store_one_line_paths() -> None:
    records = [
        {
            "key": "email.signature",
            "kind": "file",
            "value": "~/git/dotfiles/recall/snippets/email-signature.txt",
            "note": "Email signature",
            "tags": ["email"],
        }
    ]

    tree = recall.normalize_data(records, Path("data.jsonl"))

    assert recall.resolve(tree, "email.signature")["kind"] == "file"


def test_load_data_rejects_invalid_jsonl(tmp_path, monkeypatch) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "data.jsonl").write_text('{"key":\n')
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    with pytest.raises(SystemExit, match="invalid JSONL .*line 1, column 8"):
        recall.load_data({})


def test_load_data_rejects_unreadable_path(tmp_path, monkeypatch) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "data.jsonl").mkdir()
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    with pytest.raises(SystemExit, match="can't read data file .*Is a directory"):
        recall.load_data({})


def test_load_data_rejects_non_utf8_text(tmp_path, monkeypatch) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "data.jsonl").write_bytes(b"\x80")
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    with pytest.raises(SystemExit, match="data file .*must be valid UTF-8 text"):
        recall.load_data({})


def test_load_data_rejects_non_object_jsonl_line(tmp_path, monkeypatch) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "data.jsonl").write_text('"orcid.self"\n')
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    with pytest.raises(SystemExit, match="line 1 must be a JSON object"):
        recall.load_data({})


def test_load_data_preserves_physical_line_numbers_after_blank_lines(
    tmp_path, monkeypatch
) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "data.jsonl").write_text('\n{"kind": "id", "value": "x"}\n')
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    with pytest.raises(SystemExit, match="line 2 must have string field 'key'"):
        recall.load_data({})


def test_doctor_reports_invalid_jsonl_without_aborting(
    tmp_path, monkeypatch, capsys
) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "config.json").write_text(
        '{"data_file":"data.jsonl","clipboard_clear_seconds":45,"default_backend":"1password"}\n'
    )
    (recall_dir / "data.jsonl").write_text('{"key":\n')
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    status = recall.main(["doctor"])

    assert status == 1
    out = capsys.readouterr().out
    assert f"config file: {recall_dir / 'config.json'}  ✓" in out
    assert f"data file  : {recall_dir / 'data.jsonl'}  ✗ INVALID" in out
    assert "invalid JSONL" in out
    assert "line 1, column 8" in out
