import pytest

import recall


def test_init_yes_creates_default_config_and_empty_data_file(
    tmp_path, monkeypatch, capsys
) -> None:
    recall_dir = tmp_path / "recall"
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    status = recall.main(["init", "--yes", "--no-sample"])

    assert status == 0
    assert (recall_dir / "config.yaml").read_text() == (
        f"data_file: {recall_dir / 'data.yaml'}\n"
        "clipboard_clear_seconds: 45\n"
        "default_backend: 1password\n"
    )
    assert (recall_dir / "data.yaml").read_text() == ""
    assert "recall doctor" in capsys.readouterr().out


def test_init_uses_explicit_data_file_and_sample(tmp_path, monkeypatch) -> None:
    recall_dir = tmp_path / "config"
    data_file = tmp_path / "private" / "data.yaml"
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
    assert f"data_file: {data_file}\n" in (recall_dir / "config.yaml").read_text()
    assert "clipboard_clear_seconds: 0\n" in (recall_dir / "config.yaml").read_text()
    assert "orcid.self" in data_file.read_text()


def test_init_refuses_to_overwrite_existing_config(tmp_path, monkeypatch, capsys) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    config = recall_dir / "config.yaml"
    config.write_text("data_file: old.yaml\n")
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    status = recall.main(["init", "--yes"])

    assert status == 1
    assert config.read_text() == "data_file: old.yaml\n"
    assert "config already exists" in capsys.readouterr().err


def test_load_config_rejects_non_mapping_yaml(tmp_path, monkeypatch) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "config.yaml").write_text("just-a-string\n")
    monkeypatch.setenv("RECALL_DIR", str(recall_dir))

    with pytest.raises(SystemExit, match="must be a YAML mapping at the top level"):
        recall.load_config()
