from pathlib import Path

import pytest

import recall


def test_flat_dotted_keys_normalize_to_nested_tree() -> None:
    data = {
        "orcid.self": {
            "kind": "id",
            "value": "0000-0000-0000-0000",
            "tags": ["identity"],
        },
        "insurance.portal": {
            "kind": "url",
            "value": "https://example.com/login",
            "note": "Claims portal",
        },
        "github.token": {
            "kind": "secret",
            "backend": "1password",
            "ref": "op://Private/GitHub/token",
        },
    }

    tree = recall.normalize_data(data, Path("data.yaml"))

    assert recall.resolve(tree, "orcid.self")["value"] == "0000-0000-0000-0000"
    assert recall.resolve(tree, "insurance.portal")["kind"] == "url"
    assert recall.resolve(tree, "github.token")["ref"] == "op://Private/GitHub/token"
    assert sorted(key for key, _ in recall.walk_entries(tree)) == [
        "github.token",
        "insurance.portal",
        "orcid.self",
    ]


def test_nested_legacy_yaml_still_resolves() -> None:
    data = {
        "orcid": {
            "self": {
                "kind": "id",
                "value": "0000-0000-0000-0000",
            },
        },
        "github": {
            "token": {
                "kind": "secret",
                "backend": "1password",
                "ref": "op://Private/GitHub/token",
            },
        },
    }

    tree = recall.normalize_data(data, Path("facts.yaml"))

    assert recall.resolve(tree, "orcid.self")["kind"] == "id"
    assert recall.resolve(tree, "github.token")["backend"] == "1password"


def test_flat_and_nested_namespaces_can_merge() -> None:
    data = {
        "orcid.self": {
            "kind": "id",
            "value": "0000-0000-0000-0000",
        },
        "orcid": {
            "coauthor": {
                "kind": "id",
                "value": "0000-0000-0000-0001",
            },
        },
    }

    tree = recall.normalize_data(data, Path("data.yaml"))

    assert recall.resolve(tree, "orcid.self")["value"] == "0000-0000-0000-0000"
    assert recall.resolve(tree, "orcid.coauthor")["value"] == "0000-0000-0000-0001"


def test_entry_and_namespace_conflict_exits() -> None:
    data = {
        "orcid": {
            "kind": "id",
            "value": "0000-0000-0000-0000",
        },
        "orcid.self": {
            "kind": "id",
            "value": "0000-0000-0000-0001",
        },
    }

    with pytest.raises(SystemExit):
        recall.normalize_data(data, Path("data.yaml"))


def test_multiline_values_must_be_file_backed() -> None:
    data = {
        "email.signature": {
            "kind": "snippet",
            "value": "Best,\nYY\n",
            "note": "Email signature",
        },
    }

    with pytest.raises(SystemExit):
        recall.normalize_data(data, Path("data.yaml"))


def test_file_entries_store_one_line_paths() -> None:
    data = {
        "email.signature": {
            "kind": "file",
            "value": "~/git/dotfiles/recall/snippets/email-signature.txt",
            "note": "Email signature",
            "tags": ["email"],
        },
    }

    tree = recall.normalize_data(data, Path("data.yaml"))

    assert recall.resolve(tree, "email.signature")["kind"] == "file"
