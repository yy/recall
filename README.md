# recall

A small CLI **data jar** for the facts you fetch over and over — URLs, IDs,
account numbers, ORCID, reusable snippets — plus *references* to the secrets you
keep in a real vault.

You stop digging through email, password managers, and old notes for the same
account number or portal URL. You (or an agent working for you) just ask:

```console
$ recall orcid
copied orcid (id) to clipboard

$ recall uva.irb
copied uva.irb (url) to clipboard

$ recall search grant
  grants.nsf.institution-id  [account]  — NSF institution ID for the PIMS portal

$ recall github
github is a secret → op://Private/GitHub/token
  run: recall secret github   (opens it in 1Password to copy by hand)
```

---

## Contents

- [Philosophy: two tiers by threat model](#philosophy-two-tiers-by-threat-model)
- [Install](#install)
- [Quickstart](#quickstart)
- [The facts file](#the-facts-file)
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

Most "things I look up repeatedly" are not secrets. Your ORCID, an IRB portal
URL, a grant institution ID, your library card number — leaking them is not a
breach, and encrypting them behind a master password is friction with no payoff.
A few things *are* secrets: API keys, tokens, passwords.

`recall` splits data by **threat model, not by tool**:

| Tier | Examples | Where the value lives |
|---|---|---|
| **non-secret** | URLs, IDs, account numbers, ORCID, snippets | in `recall`'s plain YAML file, returned directly |
| **secret** | API keys, tokens, passwords | **only a reference** is stored; the value lives in 1Password and `recall` never reads it |

This split is the entire design. It is what lets you keep the fact file in a
(private) git repo without fear, and what lets an agent use `recall` freely
without ever being in a position to exfiltrate a credential.

---

## Install

```console
uv tool install recaller      # PyPI distribution is `recaller`; the command is `recall`
```

For the secret tier you also need the
[1Password CLI](https://developer.1password.com/docs/cli/) with desktop-app
integration turned on:

1. `brew install 1password-cli`
2. In 1Password: **Settings → Developer → Integrate with 1Password CLI** (this is
   what lets `op` unlock with Touch ID instead of a typed master password).

`recall` is macOS-first today (it uses `pbcopy` for the clipboard and `open` for
URLs and 1Password deep links).

---

## Quickstart

1. **Create a facts file** anywhere you like (a private repo is ideal):

   ```yaml
   # ~/git/dotfiles/recall/facts.yaml
   orcid:
     kind: id
     value: "0000-0002-1825-0097"
   ```

2. **Point `recall` at it** via `~/.config/recall/config.yaml`:

   ```yaml
   facts_file: ~/git/dotfiles/recall/facts.yaml
   ```

3. **Use it:**

   ```console
   $ recall orcid
   copied orcid (id) to clipboard
   $ recall doctor          # sanity-check file + environment
   ```

---

## The facts file

A single YAML file. The shape is deliberately simple:

```yaml
orcid:
  kind: id
  value: "0000-0002-1825-0097"
  note: ORCID iD

uva:                         # a namespace — no `kind:` field
  irb:
    kind: url
    value: https://example.edu/irb
    note: Use NetBadge
    tags: [research, compliance]
  computing-id:
    kind: id
    value: abc1de

github:
  kind: secret               # the value is NOT here — only a reference
  backend: 1password
  ref: op://Private/GitHub/token
  note: GitHub personal access token
```

**Entries vs namespaces.** A mapping with a `kind:` field is an **entry** (a
thing you can fetch). A mapping without one is a **namespace** that groups
entries. So `uva` is a namespace and `uva.irb` is an entry.

**Dotted paths** address the tree: `recall uva.irb`, `recall list uva`,
`recall json uva`.

**Fields:**

| Field | Applies to | Meaning |
|---|---|---|
| `kind` | all entries | `url`, `id`, `account`, `note`, `snippet`, … (free-form), or `secret` |
| `value` | non-secret entries | the value returned/copied |
| `backend` | secret entries | `1password` (default) or `keychain` |
| `ref` | secret entries | a vault reference, e.g. `op://Private/GitHub/token` |
| `note` | optional | shown in `search` / `list`; never affects the value |
| `tags` | optional | list of strings for `recall tags` |

---

## Commands

| Command | What it does |
|---|---|
| `recall <key>` | copy a non-secret value to the clipboard (shorthand for `get`) |
| `recall get <key> [--show]` | same; `--show` prints the value instead of copying |
| `recall secret <key>` | **open the item in 1Password** so you copy it by hand |
| `recall secret <key> --copy` | resolve via `op` and copy to the clipboard (auto-clears) |
| `recall secret <key> --show` | resolve and print the value (discouraged) |
| `recall open <key>` | open a `url` entry in your browser |
| `recall search <query>` | search keys, notes, and tags (never prints secret values) |
| `recall list [prefix]` | list entries, optionally under a namespace |
| `recall tags <tag>` | list entries carrying a tag |
| `recall json [key]` | dump a subtree as JSON |
| `recall doctor` | validate the facts file and environment |

Asking for a **namespace** instead of an entry lists its children:

```console
$ recall uva
uva/  (namespace)
  uva.computing-id  [id]
  uva.irb  [url]
```

---

## How secrets work

Secrets are the interesting part. `recall` is built so that **the plaintext of a
secret never passes through it**.

A secret entry stores only a reference:

```yaml
github:
  kind: secret
  backend: 1password
  ref: op://Private/GitHub/token
```

There are three ways to interact with it, in increasing order of exposure:

1. **`recall github`** (bare get) — refuses to resolve. It prints the reference
   and a hint. Nothing sensitive happens. This is safe for anyone, including an
   agent, to run.

   ```console
   $ recall github
   github is a secret → op://Private/GitHub/token
     run: recall secret github   (opens it in 1Password to copy by hand)
   ```

2. **`recall secret github`** (the default) — opens the item in the **1Password
   app** via a deep link and tells you to copy it manually. `recall` resolves the
   vault/item IDs to build the link but never reads the secret value. This is the
   recommended path: the credential goes from 1Password to your clipboard by your
   own hand, with `recall` (and any agent) entirely out of the loop.

   ```console
   $ recall secret github
   opened github in 1Password — copy the secret manually
   ```

3. **`recall secret github --copy`** (opt-in) — for scripting. This *does* run
   `op read` and place the value on the clipboard, clearing it after a timeout.
   Use it when you genuinely need the value piped somewhere; avoid it in any
   context an agent can drive.

`--show` prints the value to stdout and exists only for debugging. Don't use it
where anything is capturing your terminal.

---

## Configuration

`recall` reads `~/.config/recall/config.yaml` (override the directory with
`$XDG_CONFIG_HOME` or `$RECALL_DIR`):

```yaml
# Where the facts file actually lives. It does NOT have to be in the config dir.
facts_file: ~/git/dotfiles/recall/facts.yaml

# Seconds before a secret put on the clipboard by `--copy` is cleared.
clipboard_clear_seconds: 45

# Default vault backend for secret entries that don't set their own.
default_backend: 1password
```

**Facts-file resolution order:** `$RECALL_FILE` → `config.yaml`'s `facts_file`
→ `~/.config/recall/facts.yaml`.

A natural setup is: the **tool** is public (this repo, installable from PyPI),
while your **data** is a `facts.yaml` in a *private* repo (e.g. your dotfiles),
pointed at by `config.yaml`. The public code hardcodes nothing personal.

---

## Using recall with agents

This is the use case `recall` was built for. Give your coding agent one
instruction:

> If you need a URL, account number, identifier, or credential *reference*, use
> `recall`. Find keys with `recall search <term>` or `recall list`. Never ask me
> to paste a secret — values go to the clipboard or open in 1Password.

Then enforce the boundary in your harness instead of trusting prose. For
**Claude Code** (`~/.claude/settings.json`):

```jsonc
{
  "permissions": {
    "allow": ["Bash(recall:*)"],          // get / search / list / json / doctor — all fine
    "deny":  ["Bash(recall secret:*)"]     // only YOU resolve or open a secret
  }
}
```

With this, an agent can look up any non-secret fact unattended, but the moment it
tries `recall secret …` the harness stops it. (If you don't run in
`bypassPermissions` mode, you can use `"ask"` instead of `"deny"` to get a prompt
rather than a hard block.)

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

- The fact file is plain text by design, so keep it in a **private** repo.
  Filenames/keys are visible to anyone with repo access — don't encode anything
  sensitive in a *key name*.
- `recall` writes an access log to `~/.config/recall/audit.log` (`recall get`,
  `secret-open`, `secret-copy`, …). Review it with `tail`.
- The `.gitignore` in this repo refuses to commit a real `facts.yaml`,
  `config.yaml`, or `audit.log`, so you can't leak your jar by publishing the
  tool.

---

## Why not just …

- **`pass`?** Elegant, but it's a password-store abstraction: GPG per entry, a
  flat-ish tree, and clumsy rich metadata. `recall` keeps non-secrets in one
  readable YAML with notes/tags/kinds, and delegates *actual* secrets to a real
  vault rather than reinventing one.
- **Apple Passwords?** No scriptable read path — an agent can't fetch from it. It
  is the right home for login autofill, not for an agent-driven data jar.
- **A plain text file + `grep`?** That's most of `recall` for non-secrets — but
  you lose the secret tier, the clipboard ergonomics, the `op://` indirection,
  and the clean agent boundary.

---

## Troubleshooting

- **`no facts file at …`** — create the file and point `config.yaml`'s
  `facts_file` at it, or set `$RECALL_FILE`. Run `recall doctor`.
- **`op read failed` / `op not found`** — install the 1Password CLI and enable
  the desktop-app integration (see [Install](#install)).
- **`recall secret` opens 1Password but not the right item** — `recall` falls
  back to just launching the app when it can't resolve the item's UUID (e.g. the
  `ref` vault/item name doesn't match). Check the `ref` against
  `op item get "<item>" --vault "<vault>"`.
- **Clipboard didn't clear** — a clipboard-history manager (Raycast, Maccy,
  Paste) can retain a copy even after `recall` clears the system clipboard.
  Exclude `recall` or pause history when using `--copy`.

---

## Development

```console
git clone https://github.com/yy/recall && cd recall
uv tool install --editable . --force    # `recall` now tracks your source edits
uv run --with pyyaml recall.py doctor   # or run straight from source
```

The whole thing is one file (`recall.py`, ~350 lines) with a single runtime
dependency (PyYAML). The core lookup is a plain function, so a future MCP server
or other front-end can wrap it without going through the CLI.

## License

MIT
