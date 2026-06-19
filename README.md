# recall

A small CLI **data jar**[^datajar] for lookup data you fetch over and over: URLs, IDs, account numbers, an ORCID, reusable snippets, plus *references* to secrets kept in a real vault.

You stop digging through email, password managers, and old notes for the same account number or portal URL. You, or an agent working for you, just ask:

```console
$ recall orcid.self
copied orcid.self (id) to clipboard

$ recall insurance.portal
copied insurance.portal (url) to clipboard

$ recall search card
  library-card  [account]  — Public library card number

$ recall github.token
github.token is a secret → op://Private/GitHub/token
  run: recall secret github.token   (opens it in 1Password to copy by hand)
```

---

## Contents

- [Philosophy](#philosophy)
- [Install](#install)
- [Quickstart](#quickstart)
- [The data file](#the-data-file)
- [Multiline data](#multiline-data)
- [Commands](#commands)
- [Secrets](#secrets)
- [Configuration](#configuration)
- [Agents](#agents)
- [Security model](#security-model)
- [Why JSONL](#why-jsonl)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

---

## Philosophy

Most reusable lookup data is not secret: an ORCID, a health-insurance member ID, a portal URL, a library card number. A few items genuinely are secret: API keys, tokens, passwords.

`recall` splits data into two tiers:

| Tier | Examples | Where the value lives |
|---|---|---|
| **non-secret** | URLs, IDs, account numbers, ORCID, snippets | in a plain JSONL file, returned directly |
| **secret** | API keys, tokens, passwords | only a reference is stored; the value lives in 1Password and `recall` never reads it by default |

That split is the whole design. It lets you keep the data file in a private git repo, and lets an agent use `recall search`, `recall list`, and `recall <key>` without being able to exfiltrate credentials.

---

## Install

```console
uv tool install recaller      # PyPI distribution is `recaller`; the command is `recall`
```

For the secret tier you also need the [1Password CLI](https://developer.1password.com/docs/cli/) with desktop-app integration turned on:

1. `brew install 1password-cli`
2. In 1Password: **Settings -> Developer -> Integrate with 1Password CLI**

`recall` is macOS-first today: it uses `pbcopy` for the clipboard and `open` for URLs, files, and 1Password deep links.

---

## Quickstart

1. **Run init** and choose where the private data file should live:

   ```console
   $ recall init
   Where should recall store data.jsonl? [/Users/you/.config/recall/data.jsonl]: ~/git/dotfiles/recall/data.jsonl
   Seconds before copied secrets are cleared [45]:
   Default secret backend [1password]:
   Create a starter data file? [Y/n]:
   ```

   For a scriptable setup, pass the choices directly:

   ```console
   $ recall init --data-file ~/git/dotfiles/recall/data.jsonl --yes
   ```

2. **Add entries** to the data file:

   ```jsonl
   {"key":"orcid.self","kind":"id","value":"0000-0000-0000-0000","note":"My ORCID iD","tags":["identity"]}
   ```

3. **Use it:**

   ```console
   $ recall orcid.self
   copied orcid.self (id) to clipboard
   $ recall doctor
   ```

---

## The data file

The data file is `data.jsonl`: one JSON object per physical line. Each object is a complete entry and must include a `key` field.

```jsonl
{"key":"orcid.self","kind":"id","value":"0000-0000-0000-0000","note":"My ORCID iD","tags":["identity"]}
{"key":"orcid.coauthor","kind":"id","value":"0000-0000-0000-0001","note":"A frequent collaborator","tags":["identity"]}
{"key":"insurance.member-id","kind":"account","value":"MEMBER-ID-EXAMPLE","note":"Health insurance member ID","tags":["health"]}
{"key":"insurance.portal","kind":"url","value":"https://example.com/login","note":"Claims portal; sign in with the member ID","tags":["health"]}
{"key":"library-card","kind":"account","value":"LIBRARY-CARD-EXAMPLE","note":"Public library card number","tags":["library"]}
{"key":"github.token","kind":"secret","backend":"1password","ref":"op://Private/GitHub/token","note":"GitHub personal access token","tags":["dev"]}
```

This format is intentionally boring. The lookup key, kind, value/ref, note, and tags are on the same line, so `rg` output has enough context for a human or agent:

```console
$ rg -n 'insurance|health|member-id' ~/git/dotfiles/recall/data.jsonl
```

JSONL has no comments. Keep commentary in `note`, in a linked file, or in project docs such as `README.md` or `ROADMAP.md`. That constraint is useful here: the data file stays machine-parseable, line-oriented, and unambiguous.

**Keys and namespaces.** Dots create virtual namespaces. `insurance.member-id` and `insurance.portal` are entries; `insurance` is inferred from those prefixes. Use short lowercase keys with dots between namespaces and hyphens inside a segment: `service.account-id`, `person.orcid`, `grant.nsf.institution-id`.

**Fields:**

| Field | Applies to | Meaning |
|---|---|---|
| `key` | all entries | required dotted lookup key |
| `kind` | all entries | `url`, `file`, `id`, `account`, `note`, `snippet`, `secret`, or another free-form label |
| `value` | non-secret entries | the value returned/copied; for `file`, this is a path |
| `backend` | secret entries | `1password` (default) or `keychain` |
| `ref` | secret entries | a vault reference, e.g. `op://Private/GitHub/token` |
| `note` | optional | shown in `search` / `list`; never affects the value |
| `tags` | optional | list of strings for `recall tags` |

---

## Multiline Data

The data file is an index, not a content store. Keep each entry and each field value to one physical line.

For multiline or large reusable content, store the content in a separate file and point to it:

```jsonl
{"key":"email.reply-template","kind":"file","value":"~/git/dotfiles/recall/snippets/reply.md","note":"Standard email reply template","tags":["email"]}
```

`recall` rejects multiline `value`, `note`, `ref`, `backend`, `kind`, and tag strings. Use a `file` entry when the payload does not fit on one line.

For file-backed entries:

```console
$ recall email.reply-template --show
~/git/dotfiles/recall/snippets/reply.md

$ recall open email.reply-template
```

`recall <key>` copies the file path. `recall open <key>` opens the file with the system default app.

---

## Commands

| Command | What it does |
|---|---|
| `recall init` | create `config.json` and the first data file |
| `recall <key>` | copy a non-secret value to the clipboard |
| `recall get <key> [--show]` | same; `--show` prints the value instead of copying |
| `recall secret <key>` | open the item in 1Password so you copy it by hand |
| `recall secret <key> --copy` | resolve via `op` and copy to the clipboard (auto-clears) |
| `recall secret <key> --show` | resolve and print the value (discouraged) |
| `recall open <key>` | open a `url` or `file` entry |
| `recall search <query>` | search keys, notes, tags, and non-secret values |
| `recall list [prefix]` | list entries, optionally under a namespace |
| `recall tags <tag>` | list entries carrying a tag |
| `recall json [key]` | dump a subtree as JSON |
| `recall export` | alias for `recall json` |
| `recall doctor` | validate the data file and environment |

Asking for a namespace instead of an entry lists its children:

```console
$ recall insurance
insurance/  (namespace)
  insurance.member-id  [account]  — Health insurance member ID
  insurance.portal  [url]  — Claims portal; sign in with the member ID
```

---

## Secrets

Secrets store only a reference:

```jsonl
{"key":"github.token","kind":"secret","backend":"1password","ref":"op://Private/GitHub/token"}
```

The `op://` reference has this shape:

```text
op://<vault>/<item>/<field>
```

There are three ways to interact with a secret, in increasing order of exposure:

1. **`recall github.token`** refuses to resolve. It prints the reference and a hint.
2. **`recall secret github.token`** opens the item in the 1Password app. `recall` does not read the secret value.
3. **`recall secret github.token --copy`** runs `op read`, copies the value, and clears the clipboard after the configured timeout.

`--show` prints the value to stdout and exists only for debugging. Do not use it where anything is capturing terminal output.

Because secret entries already store `op://` references, they also work with 1Password's `op run` and `op inject`. An env file like this:

```dotenv
GITHUB_TOKEN=op://Private/GitHub/token
```

resolves at launch with `op run --env-file=.env -- your-command`. Keep `op run` to non-agent contexts, because resolved secrets live in the child process environment.

---

## Configuration

`recall` reads `~/.config/recall/config.json`. Override the directory with `$XDG_CONFIG_HOME` or `$RECALL_DIR`.

`recall init` writes this file for you:

```json
{
  "data_file": "~/git/dotfiles/recall/data.jsonl",
  "clipboard_clear_seconds": 45,
  "default_backend": "1password"
}
```

**Data-file resolution order:** `$RECALL_DATA_FILE` -> `config.json`'s `data_file` -> `~/.config/recall/data.jsonl`.

A natural setup: the **tool** is public while your **data** is a `data.jsonl` in a private repo, e.g. your dotfiles, pointed at by `config.json`. The public code hardcodes nothing personal.

---

## Agents

Give your coding agent one instruction:

> If you need a URL, account number, identifier, reusable snippet, or credential reference, use `recall`. Find keys with `recall search <term>` or `recall list`. Never ask me to paste a secret; non-secret values go to the clipboard and secrets open in 1Password.

Then enforce the boundary in your harness. For **Claude Code** (`~/.claude/settings.json`):

```jsonc
{
  "permissions": {
    "allow": ["Bash(recall:*)"],
    "deny": ["Bash(recall secret:*)"]
  }
}
```

With this, an agent can look up non-secret data unattended, but secret resolution stays gated.

---

## Security Model

| Actor | Sees a non-secret | Sees a secret value |
|---|---|---|
| `recall <key>` | yes | no, it prints the reference only |
| `recall secret <key>` | - | no, it opens the vault app |
| `recall secret <key> --copy` | - | transiently, via `op`, to clipboard |
| an agent allowed `recall` but denied `recall secret` | yes | never |
| 1Password | - | yes |

Other properties:

- The data file is plain text by design, so keep it in a private repo. Filenames and keys are visible to anyone with repo access; do not encode secrets in key names.
- `recall` logs access to `~/.config/recall/audit.log`.
- The repo's `.gitignore` refuses to commit a real `data.jsonl`, `config.json`, older local data/config filenames, or `audit.log`.

---

## Why JSONL

- **One entry per line.** Grep hits are self-contained.
- **Strict parser.** No aliases, implicit typing, or layout-sensitive nesting.
- **Append and review friendly.** A new entry is a one-line diff.
- **Portable.** Every language can parse JSON without an extra dependency.
- **Clear escape hatch.** Multiline content belongs in a linked file, not inside the index.

Compared with a plain text file plus `grep`, the CLI adds validation, clipboard ergonomics, namespace listing, JSON export, `op://` indirection, and the agent-safe split between `recall` and `recall secret`.

---

## Troubleshooting

- **`no data file at ...`**: create the file and point `config.json`'s `data_file` at it, or set `$RECALL_DATA_FILE`, then run `recall doctor`.
- **`invalid JSONL ...`**: each nonblank line must be one complete JSON object. Run `recall doctor` after edits.
- **`op read failed` / `op not found`**: install the 1Password CLI and enable the desktop-app integration.
- **`recall secret` opens 1Password but not the right item**: check the `ref` against `op item get "<item>" --vault "<vault>"`.
- **Clipboard did not clear**: clipboard-history managers can keep copies after `recall` clears the system clipboard. Exclude `recall` or pause history when using `--copy`.

---

## Development

```console
git clone https://github.com/yy/recall && cd recall
uv tool install --editable . --force
uv run python recall.py doctor
uv run pytest
```

The core is one Python file (`recall.py`) and has no runtime package dependencies. The lookup layer is plain functions, so a future MCP server or other front-end can wrap it without going through the CLI.

## License

MIT

[^datajar]: The idea is inspired by [Data Jar](https://datajar.app/).
