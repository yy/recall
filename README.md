# recall

A small CLI **data jar**[^datajar] for lookup data you fetch over and over—URLs, IDs, account numbers, an ORCID, reusable snippets—plus *references* to the secrets you keep in a real vault.

You stop digging through email, password managers, and old notes for the same account number or portal URL. You (or an agent working for you) just ask:

```console
$ recall orcid.self
copied orcid.self (id) to clipboard

$ recall orcid.coauthor
copied orcid.coauthor (id) to clipboard

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

- [Philosophy: two tiers by threat model](#philosophy-two-tiers-by-threat-model)
- [Install](#install)
- [Quickstart](#quickstart)
- [The data file](#the-data-file)
- [One-line values and file-backed data](#one-line-values-and-file-backed-data)
- [Commands](#commands)
- [How secrets work](#how-secrets-work)
- [Configuration](#configuration)
- [Using recall with agents](#using-recall-with-agents)
- [Security model](#security-model)
- [Why not just …](#why-not-just-)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

---

## Philosophy: two tiers by threat model

Most of what you look up repeatedly isn't secret: an ORCID, a health-insurance member ID, a portal URL you hit twice a year, a library card number. Leaking these isn't a breach, and locking them behind a master password is friction with no payoff. A few items genuinely are secret: API keys, tokens, passwords.

`recall` splits data into two tiers, secrets and non-secrets:

| Tier | Examples | Where the value lives |
|---|---|---|
| **non-secret** | URLs, IDs, account numbers, ORCID, snippets | in `recall`'s plain YAML file, returned directly |
| **secret** | API keys, tokens, passwords | **only a reference** is stored; the value lives in 1Password and `recall` never reads it |

That split is the whole design. It lets you keep the data file in a private git repo without worry, and lets an agent use `recall` freely without ever being able to exfiltrate a credential.

---

## Install

```console
uv tool install recaller      # PyPI distribution is `recaller`; the command is `recall`
```

For the secret tier you also need the [1Password CLI](https://developer.1password.com/docs/cli/) with desktop-app integration turned on:

1. `brew install 1password-cli`
2. In 1Password: **Settings → Developer → Integrate with 1Password CLI** (this is what lets `op` unlock with Touch ID instead of a typed master password).

`recall` is macOS-first today: it uses `pbcopy` for the clipboard and `open` for URLs and 1Password deep links.

---

## Quickstart

1. **Run init** and choose where the private data file should live:

   ```console
   $ recall init
   Where should recall store data.yaml? [/Users/you/.config/recall/data.yaml]: ~/git/dotfiles/recall/data.yaml
   Seconds before copied secrets are cleared [45]:
   Default secret backend [1password]:
   Create a starter data file? [Y/n]:
   ```

   For a scriptable setup, pass the choices directly:

   ```console
   $ recall init --data-file ~/git/dotfiles/recall/data.yaml --yes
   ```

2. **Add entries** to the data file:

   ```yaml
   orcid.self: {kind: id, value: "0000-0000-0000-0000", note: "My ORCID iD"}
   ```

3. **Use it:**

   ```console
   $ recall orcid.self
   copied orcid.self (id) to clipboard
   $ recall doctor          # sanity-check file + environment
   ```

---

## The data file

The recommended data file is a flat YAML mapping: one dotted key per entry, one entry per line. This keeps the file easy for humans and agents to scan with `rg`, while still giving `recall` a real parser instead of a pile of shell parsing rules.

```yaml
orcid.self: {kind: id, value: "0000-0000-0000-0000", note: "My ORCID iD", tags: [identity]}
orcid.coauthor: {kind: id, value: "0000-0000-0000-0000", note: "A frequent collaborator", tags: [identity]}

insurance.member-id: {kind: account, value: "MEMBER-ID-EXAMPLE", note: "Health insurance member ID", tags: [health]}
insurance.portal: {kind: url, value: "https://example.com/login", note: "Claims portal; sign in with the member ID", tags: [health]}

library-card: {kind: account, value: "LIBRARY-CARD-EXAMPLE", note: "Public library card number", tags: [library]}

github.token: {kind: secret, backend: 1password, ref: "op://Private/GitHub/token", note: "GitHub personal access token", tags: [dev]}
```

This is still YAML, but it uses YAML's inline mapping form. The first token on each line is the canonical lookup key; the rest of the line contains all grep-relevant metadata. For example:

```console
$ rg -n 'insurance|health|member-id' ~/git/dotfiles/recall/data.yaml
```

That property is the main reason to prefer flat YAML over nested YAML here. In nested YAML, the key, kind, value, note, and tags are spread across different lines, so a simple grep result often lacks enough context for an agent to act on confidently.

**Keys and namespaces.** Dots create virtual namespaces. `insurance.member-id` and `insurance.portal` are entries; `insurance` is a namespace inferred from those prefixes. Use short lowercase keys with dots between namespaces and hyphens inside a segment: `service.account-id`, `person.orcid`, `grant.nsf.institution-id`.

**Dotted paths** address the tree: `recall insurance.portal`, `recall list insurance`, `recall json insurance`.

Nested YAML is still accepted for compatibility. Internally, `recall` normalizes flat dotted keys and nested YAML to the same tree.

**Fields:**

| Field | Applies to | Meaning |
|---|---|---|
| `kind` | all entries | `url`, `file`, `id`, `account`, `note`, `snippet`, … (free-form), or `secret` |
| `value` | non-secret entries | the value returned/copied; for `file`, this is a path |
| `backend` | secret entries | `1password` (default) or `keychain` |
| `ref` | secret entries | a vault reference, e.g. `op://Private/GitHub/token` |
| `note` | optional | shown in `search` / `list`; never affects the value |
| `tags` | optional | list of strings for `recall tags` |

---

## One-line values and file-backed data

The data file is an index, not a content store. Keep each entry and each field value to one physical line.

For multiline or large reusable content, store the content in a separate file and point to it:

```yaml
email.reply-template: {kind: file, value: "~/git/dotfiles/recall/snippets/reply.md", note: "Standard email reply template", tags: [email]}
```

That keeps `data.yaml` grep-friendly and keeps each search hit self-contained. `recall` rejects multiline `value`, `note`, `ref`, `backend`, `kind`, and tag strings; use `kind: file` when the payload does not fit on one line.

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
| `recall init` | create `config.yaml` and the first data file |
| `recall <key>` | copy a non-secret value to the clipboard (shorthand for `get`) |
| `recall get <key> [--show]` | same; `--show` prints the value instead of copying |
| `recall secret <key>` | **open the item in 1Password** so you copy it by hand |
| `recall secret <key> --copy` | resolve via `op` and copy to the clipboard (auto-clears) |
| `recall secret <key> --show` | resolve and print the value (discouraged) |
| `recall open <key>` | open a `url` or `file` entry |
| `recall search <query>` | search keys, notes, and tags (never prints secret values) |
| `recall list [prefix]` | list entries, optionally under a namespace |
| `recall tags <tag>` | list entries carrying a tag |
| `recall json [key]` | dump a subtree as JSON |
| `recall export` | alias for `recall json` (whole tree) |
| `recall doctor` | validate the data file and environment |
| `recall help` | show usage |

Asking for a **namespace** instead of an entry lists its children:

```console
$ recall insurance
insurance/  (namespace)
  insurance.member-id  [account]  — Health insurance member ID
  insurance.portal  [url]  — Claims portal; sign in with the member ID
```

---

## How secrets work

Secrets are the interesting part. `recall` is built so that **the plaintext of a secret never passes through it**.

A secret entry stores only a reference:

```yaml
github.token: {kind: secret, backend: 1password, ref: "op://Private/GitHub/token"}
```

### Creating the 1Password reference

First store the secret itself in 1Password, usually as a Password or API Credential item. Put it in the vault you want to use, give the item a stable name, and put the actual credential in the field you want `op` to read. 1Password's default password/token field is usually named `password` or `credential`.

The `op://` reference has this shape:

```text
op://<vault>/<item>/<field>
```

For example, if the vault is `Private`, the item is `GitHub`, and the token is in a field named `token`, use:

```yaml
github.token: {kind: secret, backend: 1password, ref: "op://Private/GitHub/token"}
```

To check the field names, run:

```console
$ op item get GitHub --vault Private
```

Use the visible field label in the final path segment. If names contain spaces, keep them in the reference exactly as 1Password shows them, or rename the item/field to something simple like `token` to make the reference grep-friendly.

There are three ways to interact with it, in increasing order of exposure:

1. **`recall github.token`** (bare get) refuses to resolve. It prints the reference and a hint; nothing sensitive happens. Safe for anyone, including an agent, to run.

   ```console
   $ recall github.token
   github.token is a secret → op://Private/GitHub/token
     run: recall secret github.token   (opens it in 1Password to copy by hand)
   ```

2. **`recall secret github.token`** (the default) opens the item in the **1Password app** via a deep link and tells you to copy it manually. `recall` resolves the vault and item IDs to build the link but never reads the secret value. This is the recommended path: the credential goes from 1Password to your clipboard by your own hand, with `recall` (and any agent) out of the loop.

   ```console
   $ recall secret github.token
   opened github.token in 1Password — copy the secret manually
   ```

3. **`recall secret github.token --copy`** (opt-in) is for scripting. It *does* run `op read` and place the value on the clipboard, clearing it after a timeout. Use it when you genuinely need the value piped somewhere; avoid it in any context an agent can drive.

`--show` prints the value to stdout and exists only for debugging. Don't use it where anything is capturing your terminal.

### Working with `op run`

Because secret entries already store `op://` references, they slot straight into 1Password's [`op run`](https://developer.1password.com/docs/cli/reference/commands/run/) and `op inject`. A `recall` `ref` is exactly the string those commands expect, so an env file like

```dotenv
GITHUB_TOKEN=op://Private/GitHub/token
```

resolves at launch with `op run --env-file=.env -- your-command`. `recall` stays the interactive path (open in the app, or `--copy` one value); `op run` covers bulk, non-interactive injection. Keep `op run` to non-agent contexts, though: it places resolved secrets in the child process's environment, where an agent driving that process could read them.

Right now `recall` supports **1Password only** as a secret backend. (A `keychain` backend exists for `--copy`, but the app deep link and `op run` are 1Password-specific.)

---

## Configuration

`recall` reads `~/.config/recall/config.yaml` (override the directory with `$XDG_CONFIG_HOME` or `$RECALL_DIR`):

`recall init` writes this file for you. Edit it directly only when you want to move the data file or change defaults.

```yaml
# Where the data file actually lives. It does NOT have to be in the config dir.
data_file: ~/git/dotfiles/recall/data.yaml

# Seconds before a secret put on the clipboard by `--copy` is cleared.
clipboard_clear_seconds: 45

# Default vault backend for secret entries that don't set their own.
default_backend: 1password
```

**Data-file resolution order:** `$RECALL_DATA_FILE` → `$RECALL_FILE` → `config.yaml`'s `data_file` → legacy `facts_file` → `~/.config/recall/data.yaml` → legacy `~/.config/recall/facts.yaml`.

A natural setup: the **tool** is public (this repo, installable from PyPI) while your **data** is a `data.yaml` in a private repo, e.g. your dotfiles, pointed at by `config.yaml`. The public code hardcodes nothing personal.

---

## Using recall with agents

This is the use case `recall` was built for. Give your coding agent one instruction:

> If you need a URL, account number, identifier, or credential *reference*, use `recall`. Find keys with `recall search <term>` or `recall list`. Never ask me to paste a secret; values go to the clipboard or open in 1Password.

Then enforce the boundary in your harness instead of trusting prose. For **Claude Code** (`~/.claude/settings.json`):

```jsonc
{
  "permissions": {
    "allow": ["Bash(recall:*)"],          // get / search / list / json / doctor — all fine
    "deny":  ["Bash(recall secret:*)"]     // only YOU resolve or open a secret
  }
}
```

With this, an agent can look up any non-secret data unattended, but the moment it tries `recall secret …` the harness stops it. (If you don't run in `bypassPermissions` mode, use `"ask"` instead of `"deny"` for a prompt rather than a hard block.)

---

## Security model

What touches a secret's plaintext, and what doesn't:

| Actor | Sees a non-secret | Sees a secret value |
|---|---|---|
| `recall <key>` | yes (returns it) | **no** (prints the reference only) |
| `recall secret <key>` (default) | — | **no** (opens the app; you copy) |
| `recall secret <key> --copy` | — | transiently, via `op`, to clipboard |
| an agent allowed `recall` but denied `recall secret` | yes | **never** |
| 1Password | — | yes (it is the vault) |

Other properties:

- The data file is plain text by design, so keep it in a **private** repo. Filenames and keys are visible to anyone with repo access; don't encode anything sensitive in a *key name*.
- `recall` logs every access to `~/.config/recall/audit.log` (`get`, `secret-open`, `secret-copy`, …). Review it with `tail`.
- The repo's `.gitignore` refuses to commit a real `data.yaml`, legacy `facts.yaml`, `config.yaml`, or `audit.log`, so publishing the tool can't leak your jar.

---

## Why not just …

- **`pass`?** Elegant, but it's a password-store abstraction: GPG per entry, a flattish tree, clumsy rich metadata. `recall` keeps non-secrets in one grep-friendly YAML file with notes, tags, and kinds, and delegates *actual* secrets to a real vault instead of reinventing one.
- **Apple Passwords?** No scriptable read path, so an agent can't fetch from it. It's the right home for login autofill, not for an agent-driven data jar.
- **A plain text file plus `grep`?** That's most of `recall` for non-secrets, which is why the recommended format is one entry per line. The CLI adds structured validation, clipboard ergonomics, `op://` indirection, and the clean agent boundary.

---

## Troubleshooting

- **`no data file at …`**: create the file and point `config.yaml`'s `data_file` at it, or set `$RECALL_DATA_FILE`, then run `recall doctor`.
- **`op read failed` / `op not found`**: install the 1Password CLI and enable the desktop-app integration (see [Install](#install)).
- **`recall secret` opens 1Password but not the right item**: `recall` falls back to launching the app when it can't resolve the item's UUID (e.g. the `ref`'s vault or item name doesn't match). Check the `ref` against `op item get "<item>" --vault "<vault>"`.
- **Clipboard didn't clear**: a clipboard-history manager (Raycast, Maccy, Paste) can keep a copy even after `recall` clears the system clipboard. Exclude `recall` or pause history when using `--copy`.

---

## Development

```console
git clone https://github.com/yy/recall && cd recall
uv tool install --editable . --force    # `recall` now tracks your source edits
uv run --with pyyaml recall.py doctor   # or run straight from source
uv run pytest
```

The whole thing is one file (`recall.py`) with a single runtime dependency, PyYAML. The core lookup is a plain function, so a future MCP server or other front-end can wrap it without going through the CLI.

## License

MIT

[^datajar]: The idea is inspired by [Data Jar](https://datajar.app/).
