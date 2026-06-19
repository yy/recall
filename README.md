# recall

A small CLI **data jar** for the facts you fetch over and over — URLs, IDs,
account numbers, ORCID, reusable snippets — plus *references* to the secrets
you keep in a real vault.

```console
$ recall orcid
copied orcid (id) to clipboard

$ recall uva.irb
copied uva.irb (url) to clipboard

$ recall search grant
  grants.nsf.institution-id  [account]  — NSF institution ID for the PIMS portal

$ recall github
github is a secret → op://Private/GitHub/token
  run: recall secret github

$ recall secret github
copied github to clipboard (clears in 45s)
```

## Why two tiers

`recall` splits data by **threat model**, not by tool:

| Tier | Examples | Where it lives |
|---|---|---|
| **non-secret** | URLs, IDs, account numbers, ORCID, snippets | this YAML file, returned directly |
| **secret** | API keys, tokens, passwords | **only a reference** is stored here; the value lives in 1Password (or Keychain) and is resolved on demand |

The bare `recall <key>` form **never resolves a secret** — it prints the
reference and tells you to use `recall secret`. That split is the whole point:
an agent can be allowed `recall` / `search` / `list` freely, while
`recall secret` stays gated behind explicit permission (and your vault's
biometric unlock).

## Install

```console
uv tool install recaller     # provides the `recall` command
# or, from a checkout:
uv tool install --from . recaller
```

For secret resolution you need the [1Password CLI](https://developer.1password.com/docs/cli/)
(`op`) with the desktop-app integration enabled (Settings → Developer →
*Integrate with 1Password CLI*).

## Setup

`recall` reads `~/.config/recall/config.yaml`. The facts file does **not** have
to live in the config dir — point at it from there (e.g. a private dotfiles
repo):

```yaml
# ~/.config/recall/config.yaml
facts_file: ~/git/dotfiles/recall/facts.yaml
clipboard_clear_seconds: 45
default_backend: 1password
```

Resolution order for the facts file: `$RECALL_FILE` → `config.yaml`'s
`facts_file` → `~/.config/recall/facts.yaml`.

## Data model

```yaml
orcid:
  kind: id
  value: "0000-0002-1825-0097"

uva:                       # a namespace (no `kind:`)
  irb:
    kind: url
    value: https://example.edu/irb
    note: Use NetBadge
    tags: [research]

github:
  kind: secret             # value is NOT stored — only the reference
  backend: 1password
  ref: op://Private/GitHub/token
```

- A mapping with a `kind:` field is an **entry**; one without is a **namespace**.
- Dotted paths address the tree: `recall uva.irb`, `recall list uva`.
- `kind`: `url`, `id`, `account`, `note`, `snippet`, … (free-form) or `secret`.
- Non-secret entries carry `value`; secret entries carry `backend` + `ref`.
- Optional metadata: `note`, `tags`.

## Commands

| Command | Does |
|---|---|
| `recall <key>` | copy a non-secret value to the clipboard (alias for `get`) |
| `recall get <key> [--show]` | same; `--show` prints instead of copying |
| `recall secret <key> [--show]` | resolve a secret reference via the vault → clipboard (auto-clears) |
| `recall open <key>` | open a `url` entry in the browser |
| `recall search <query>` | search keys, notes and tags (never prints secret values) |
| `recall list [prefix]` | list entries, optionally under a namespace |
| `recall tags <tag>` | list entries carrying a tag |
| `recall json [key]` | dump a subtree as JSON |
| `recall doctor` | validate the facts file and environment |

## Use with agents

Tell your agent:

> If you need a URL, account number, identifier, or credential reference, use
> `recall`. Use `recall search <term>` to find a key. Never ask me to paste a
> secret — values go to the clipboard.

Then gate the secret path in your harness — e.g. Claude Code `settings.json`:
allow `recall`, `recall search`, `recall list`; **prompt** on `recall secret`.

## License

MIT
