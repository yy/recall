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


def test_init_relative_data_file_is_resolved_from_config_dir(
    tmp_path, monkeypatch
) -> None:
    recall_dir = tmp_path / "config"
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    status = recall.main(
        ["init", "--yes", "--data-file", "private/data.jsonl", "--sample"]
    )

    assert status == 0
    assert json.loads((recall_dir / "config.json").read_text()) == {
        "data_file": "private/data.jsonl",
        "clipboard_clear_seconds": 45,
        "default_backend": "1password",
    }
    assert (recall_dir / "private" / "data.jsonl").exists()

    monkeypatch.chdir(tmp_path)
    data = recall.load_data(recall.load_config())

    assert recall.resolve(data, "orcid.self")["value"] == "0000-0000-0000-0000"


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


def test_init_rejects_config_path_that_is_a_directory(
    tmp_path, monkeypatch, capsys
) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "config.json").mkdir()
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    status = recall.main(["init", "--yes", "--force", "--no-sample"])

    assert status == 1
    assert "config file path must be a file" in capsys.readouterr().err


def test_init_rejects_data_file_path_that_is_a_directory(
    tmp_path, monkeypatch, capsys
) -> None:
    recall_dir = tmp_path / "recall"
    data_dir = tmp_path / "private" / "data.jsonl"
    data_dir.mkdir(parents=True)
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    status = recall.main(
        ["init", "--yes", "--data-file", str(data_dir), "--no-sample"]
    )

    assert status == 1
    assert "data file path must be a file" in capsys.readouterr().err


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


def test_load_config_rejects_unreadable_path(tmp_path, monkeypatch) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "config.json").mkdir()
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    with pytest.raises(SystemExit, match="can't read config file .*Is a directory"):
        recall.load_config()


def test_load_config_rejects_non_utf8_text(tmp_path, monkeypatch) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "config.json").write_bytes(b"\x80")
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    with pytest.raises(SystemExit, match="config file .*must be valid UTF-8 text"):
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


def test_load_config_rejects_non_string_data_file(tmp_path, monkeypatch) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "config.json").write_text('{"data_file":123}\n')
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    with pytest.raises(SystemExit, match="field 'data_file' must be a string"):
        recall.load_config()


def test_load_config_rejects_non_string_default_backend(
    tmp_path, monkeypatch
) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "config.json").write_text('{"default_backend":true}\n')
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    with pytest.raises(SystemExit, match="field 'default_backend' must be a string"):
        recall.load_config()


def test_load_config_rejects_unknown_default_backend(
    tmp_path, monkeypatch
) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "config.json").write_text('{"default_backend":"vaulty"}\n')
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    with pytest.raises(
        SystemExit,
        match="field 'default_backend' must be one of: 1password, keychain, op",
    ):
        recall.load_config()


def test_init_force_recovers_from_invalid_existing_config(
    tmp_path, monkeypatch, capsys
) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "config.json").write_text('{"broken":\n')
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    status = recall.main(["init", "--yes", "--force", "--no-sample"])

    assert status == 0
    assert json.loads((recall_dir / "config.json").read_text()) == {
        "data_file": str(recall_dir / "data.jsonl"),
        "clipboard_clear_seconds": 45,
        "default_backend": "1password",
    }
    assert "wrote config" in capsys.readouterr().out


def test_init_rejects_unknown_default_backend(
    tmp_path, monkeypatch, capsys
) -> None:
    recall_dir = tmp_path / "recall"
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    status = recall.main(
        ["init", "--yes", "--default-backend", "vaulty", "--no-sample"]
    )

    assert status == 1
    assert not (recall_dir / "config.json").exists()
    assert (
        "default backend must be one of: 1password, keychain, op"
        in capsys.readouterr().err
    )


def test_init_reports_config_write_errors(tmp_path, monkeypatch, capsys) -> None:
    recall_dir = tmp_path / "recall"
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    original_write_text = recall.Path.write_text

    def fake_write_text(self, text, *args, **kwargs):
        if self == recall_dir / "config.json":
            raise OSError(13, "Permission denied")
        return original_write_text(self, text, *args, **kwargs)

    monkeypatch.setattr(recall.Path, "write_text", fake_write_text)

    status = recall.main(["init", "--yes", "--no-sample"])

    assert status == 1
    assert "can't write config file" in capsys.readouterr().err
    assert not (recall_dir / "config.json").exists()


def test_init_reports_data_file_write_errors(tmp_path, monkeypatch, capsys) -> None:
    recall_dir = tmp_path / "recall"
    data_file = tmp_path / "private" / "data.jsonl"
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    original_write_text = recall.Path.write_text

    def fake_write_text(self, text, *args, **kwargs):
        if self == data_file:
            raise OSError(28, "No space left on device")
        return original_write_text(self, text, *args, **kwargs)

    monkeypatch.setattr(recall.Path, "write_text", fake_write_text)

    status = recall.main(
        ["init", "--yes", "--data-file", str(data_file), "--no-sample"]
    )

    captured = capsys.readouterr()
    assert status == 1
    assert "wrote config" not in captured.out
    assert "can't write data file" in captured.err
    assert not (recall_dir / "config.json").exists()
    assert not data_file.exists()


def test_audit_creates_config_dir_and_appends_log(tmp_path, monkeypatch) -> None:
    recall_dir = tmp_path / "recall"
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    recall.audit("get", "orcid.self")

    audit_log = recall_dir / "audit.log"
    assert audit_log.exists()
    assert audit_log.read_text().endswith("\tget\torcid.self\n")
