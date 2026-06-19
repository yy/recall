# Roadmap

## Near-term

- Add `recall format --check` to verify canonical compact JSONL entries.
- Add `recall format` to rewrite the data file into canonical compact JSONL.
- Make `doctor` report more precise data-file validation errors, including line-oriented guidance.
- Add tests for CLI command output, not just data loading and normalization.

## Later

- Consider `recall add` after formatter support exists.
- Consider `recall add-secret` for adding `op://` references without touching secret plaintext.
- Consider `recall add-file` for file-backed entries.
- Decide whether file entries should remain path-only or gain a `recall cat <key>` command.
- Consider `recall json --flat` for agent-friendly export.

## Design decisions

- `data.jsonl` is an index, not a content store.
- Each entry should occupy one physical line.
- Multiline or large payloads belong in linked files via file entries.
- Secret entries store references only; secret plaintext must stay in the vault.
