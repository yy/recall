import argparse

import pytest

import recall


@pytest.fixture
def search_data() -> dict:
    return {
        "library-card": {
            "kind": "account",
            "value": "LIBRARY-CARD-EXAMPLE",
            "note": "Public library card number",
            "tags": ["library", "identity"],
        },
        "insurance": {
            "portal": {
                "kind": "url",
                "value": "https://example.com/login",
                "note": "Claims portal",
                "tags": ["health"],
            }
        },
        "github": {
            "token": {
                "kind": "secret",
                "backend": "1password",
                "ref": "op://Private/GitHub/token",
                "note": "GitHub personal access token",
                "tags": ["dev"],
            }
        },
    }


@pytest.mark.parametrize(
    ("query", "expected_line", "hidden_text"),
    [
        ("library-card", "  library-card  [account]  — Public library card number", "LIBRARY-CARD-EXAMPLE"),
        ("claims", "  insurance.portal  [url]  — Claims portal", "https://example.com/login"),
        ("health", "  insurance.portal  [url]  — Claims portal", "https://example.com/login"),
        ("github", "  github.token  [secret]  — GitHub personal access token", "op://Private/GitHub/token"),
    ],
)
def test_search_matches_documented_fields_without_printing_hidden_values(
    monkeypatch, capsys, search_data, query, expected_line, hidden_text
) -> None:
    monkeypatch.setattr(recall, "load_data", lambda cfg: search_data)

    status = recall.cmd_search(argparse.Namespace(query=query), {})

    assert status == 0
    output = capsys.readouterr().out
    assert expected_line in output
    assert hidden_text not in output


def test_search_does_not_match_secret_refs(monkeypatch, capsys, search_data) -> None:
    monkeypatch.setattr(recall, "load_data", lambda cfg: search_data)

    status = recall.cmd_search(argparse.Namespace(query="Private/GitHub/token"), {})

    assert status == 1
    captured = capsys.readouterr()
    assert captured.out == "recall: no matches for 'Private/GitHub/token'\n"
    assert captured.err == ""
