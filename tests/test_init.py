import json

import pytest

import recall


def test_init_yes_creates_default_config_and_empty_data_file(
    tmp_path, monkeypatch, capsys
) -> None:
    recall_dir = tmp_path / "recall"
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    status = recall.main(["init", "--yes", "--no-sample"])

    assert status == 0
    assert json.loads((recall_dir / "config.json").read_text()) == {
        "data_file": str(recall_dir / "data.jsonl"),
        "clipboard_clear_seconds": 45,
        "default_backend": "1password",
    }
    assert (recall_dir / "data.jsonl").read_text() == ""
    assert "recall doctor" in capsys.readouterr().out


def test_init_uses_explicit_data_file_and_sample(tmp_path, monkeypatch) -> None:
    recall_dir = tmp_path / "config"
    data_file = tmp_path / "private" / "data.jsonl"
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    status = recall.main(
        [
            "init",
            "--yes",
            "--data-file",
            str(data_file),
            "--clipboard-clear-seconds",
            "0",
            "--sample",
        ]
    )

    assert status == 0
    assert json.loads((recall_dir / "config.json").read_text()) == {
        "data_file": str(data_file),
        "clipboard_clear_seconds": 0,
        "default_backend": "1password",
    }
    assert "orcid.self" in data_file.read_text()


def test_init_refuses_to_overwrite_existing_config(tmp_path, monkeypatch, capsys) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    config = recall_dir / "config.json"
    config.write_text('{"data_file":"old.jsonl"}\n')
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    status = recall.main(["init", "--yes"])

    assert status == 1
    assert config.read_text() == '{"data_file":"old.jsonl"}\n'
    assert "config already exists" in capsys.readouterr().err


def test_load_config_rejects_non_object_json(tmp_path, monkeypatch) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "config.json").write_text('"just-a-string"\n')
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    with pytest.raises(SystemExit, match="must be a JSON object"):
        recall.load_config()


def test_load_config_rejects_invalid_json(tmp_path, monkeypatch) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "config.json").write_text('{"broken":\n')
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    with pytest.raises(
        SystemExit, match="invalid JSON in config file .*line 2, column 1"
    ):
        recall.load_config()


def test_load_config_rejects_non_integer_clipboard_clear_seconds(
    tmp_path, monkeypatch
) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "config.json").write_text('{"clipboard_clear_seconds":"45"}\n')
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    with pytest.raises(
        SystemExit, match="field 'clipboard_clear_seconds' must be an integer"
    ):
        recall.load_config()


def test_load_config_rejects_negative_clipboard_clear_seconds(
    tmp_path, monkeypatch
) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "config.json").write_text('{"clipboard_clear_seconds":-1}\n')
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    with pytest.raises(
        SystemExit, match="field 'clipboard_clear_seconds' must be non-negative"
    ):
        recall.load_config()
