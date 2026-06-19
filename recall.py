"""recall — a small CLI "data jar" for lookup data you fetch over and over.

Two tiers, by threat model:

  * non-secrets (URLs, IDs, account numbers, ORCID, reusable snippets) live in
    a plain YAML file and are returned directly;
  * secrets (API keys, tokens, passwords) are NEVER stored here — only a
    reference to a vault (e.g. ``op://Private/GitHub/token``) is stored, and the
    value is resolved on demand via ``recall secret``.

The bare ``recall <key>`` form copies a non-secret value to the clipboard. It
will not resolve a secret: it prints the reference and tells you to use
``recall secret``. That split is the whole security model — an agent can be
allowed ``recall``/``search``/``list`` freely while ``recall secret`` stays
gated.

Data model (``data.yaml``): one line per dotted key, with an inline YAML map::

    orcid.self: {kind: id, value: "0000-0000-0000-0000", note: "My ORCID iD"}
    uva.irb: {kind: url, value: "https://...", note: "Use NetBadge"}
    github.token: {kind: secret, backend: 1password, ref: "op://Private/GitHub/token"}

Nested YAML mappings are still accepted for compatibility. A mapping with a
``kind:`` field is an *entry*; one without is a *namespace*.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("recall: PyYAML is required (pip install pyyaml)")

__version__ = "0.1.0"

SECRET_KINDS = {"secret"}
# A node is an entry if it is a mapping carrying one of these marker fields.
ENTRY_MARKERS = ("kind", "value", "ref")

DEFAULT_CONFIG = {
    "clipboard_clear_seconds": 45,
    "default_backend": "1password",
}


# --------------------------------------------------------------------------- #
# Paths & loading
# --------------------------------------------------------------------------- #
def config_dir() -> Path:
    if env := os.environ.get("RECALL_DIR"):
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME", "~/.config")
    return Path(base).expanduser() / "recall"


def data_path(cfg: dict) -> Path:
    """Find the data file, with legacy facts-file names kept as fallbacks.

    The data file does not have to live in the config dir; config.yaml just
    points at wherever it actually is (e.g. a private dotfiles repo).
    """
    if env := os.environ.get("RECALL_DATA_FILE"):
        return Path(env).expanduser()
    if env := os.environ.get("RECALL_FILE"):
        return Path(env).expanduser()
    if cfg.get("data_file"):
        return Path(str(cfg["data_file"])).expanduser()
    if cfg.get("facts_file"):
        return Path(str(cfg["facts_file"])).expanduser()
    preferred = config_dir() / "data.yaml"
    if preferred.exists():
        return preferred
    legacy = config_dir() / "facts.yaml"
    if legacy.exists():
        return legacy
    return preferred


def load_config() -> dict:
    path = config_dir() / "config.yaml"
    cfg = dict(DEFAULT_CONFIG)
    if path.exists():
        loaded = yaml.safe_load(path.read_text()) or {}
        cfg.update(loaded)
    return cfg


def load_data(cfg: dict) -> dict:
    path = data_path(cfg)
    if not path.exists():
        sys.exit(
            f"recall: no data file at {path}\n"
            f"point config.yaml 'data_file' at it, set RECALL_DATA_FILE, or see 'recall doctor'."
        )
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        sys.exit(f"recall: {path} must be a YAML mapping at the top level")
    normalized = normalize_data(data, path)
    validate_tree(normalized, "", path)
    return normalized


def normalize_data(data: dict, path: Path) -> dict:
    """Convert flat dotted keys to the same tree shape as nested YAML."""
    root: dict[str, Any] = {}
    for key, node in data.items():
        if not isinstance(key, str):
            sys.exit(f"recall: {path}: top-level keys must be strings")
        parts = key.split(".")
        if any(not part for part in parts):
            sys.exit(f"recall: {path}: invalid empty key segment in '{key}'")
        insert_entry(root, parts, node, key, path)
    return root


def insert_entry(root: dict, parts: list[str], node: Any, key: str, path: Path) -> None:
    cursor = root
    for part in parts[:-1]:
        existing = cursor.setdefault(part, {})
        if is_entry(existing) or not isinstance(existing, dict):
            sys.exit(f"recall: {path}: '{key}' conflicts with entry '{part}'")
        cursor = existing
    leaf = parts[-1]
    if leaf in cursor:
        cursor[leaf] = merge_nodes(cursor[leaf], node, key, path)
    else:
        cursor[leaf] = node


def merge_nodes(existing: Any, incoming: Any, key: str, path: Path) -> Any:
    if not (
        isinstance(existing, dict)
        and isinstance(incoming, dict)
        and not is_entry(existing)
        and not is_entry(incoming)
    ):
        sys.exit(f"recall: {path}: duplicate or conflicting entry for '{key}'")
    merged = dict(existing)
    for child_key, child_node in incoming.items():
        if child_key in merged:
            merged[child_key] = merge_nodes(merged[child_key], child_node, key, path)
        else:
            merged[child_key] = child_node
    return merged


def validate_tree(node: Any, dotted: str, path: Path) -> None:
    if is_entry(node):
        return
    if not isinstance(node, dict):
        label = dotted or "<root>"
        sys.exit(
            f"recall: {path}: '{label}' is neither an entry mapping nor a namespace"
        )
    for key, child in node.items():
        child_path = f"{dotted}.{key}" if dotted else str(key)
        validate_tree(child, child_path, path)


# --------------------------------------------------------------------------- #
# Tree helpers
# --------------------------------------------------------------------------- #
def is_entry(node: Any) -> bool:
    return isinstance(node, dict) and any(k in node for k in ENTRY_MARKERS)


def resolve(data: dict, dotted: str) -> Any:
    """Walk a dotted path. Returns the node, or None if not found."""
    node: Any = data
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def walk_entries(data: dict, prefix: str = ""):
    """Yield (dotted_key, entry_dict) for every entry in the tree."""
    for key, node in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if is_entry(node):
            yield path, node
        elif isinstance(node, dict):
            yield from walk_entries(node, path)


def entry_value(entry: dict) -> Any:
    return entry.get("value")


def entry_kind(entry: dict) -> str:
    if "kind" in entry:
        return entry["kind"]
    return "secret" if "ref" in entry else "value"


def entry_tags(entry: dict) -> list[str]:
    tags = entry.get("tags") or []
    if isinstance(tags, list):
        return [str(tag) for tag in tags]
    return [str(tags)]


def one_line(text: Any) -> str:
    return " ".join(str(text).split())


# --------------------------------------------------------------------------- #
# Side effects: clipboard, audit, vault
# --------------------------------------------------------------------------- #
def to_clipboard(text: str, clear_after: int | None = None) -> None:
    if not shutil.which("pbcopy"):
        sys.exit("recall: pbcopy not found (macOS only for now)")
    subprocess.run(["pbcopy"], input=text.encode(), check=True)
    if clear_after and clear_after > 0:
        # Detached: clear the clipboard later only if it still holds our value.
        script = (
            f"sleep {int(clear_after)}; "
            f"current=$(pbpaste); "
            f'if [ "$current" = "$(cat)" ]; then printf "" | pbcopy; fi'
        )
        subprocess.Popen(
            ["sh", "-c", script],
            stdin=subprocess.PIPE,
            start_new_session=True,
        ).stdin.write(text.encode())  # type: ignore[union-attr]


def audit(command: str, key: str) -> None:
    path = config_dir() / "audit.log"
    stamp = _dt.datetime.now().isoformat(timespec="seconds")
    try:
        with path.open("a") as fh:
            fh.write(f"{stamp}\t{command}\t{key}\n")
    except OSError:
        pass  # never let audit failure block a lookup


def vault_read(entry: dict, cfg: dict) -> str:
    backend = entry.get("backend", cfg.get("default_backend", "1password"))
    ref = entry.get("ref")
    if not ref:
        sys.exit("recall: secret entry has no 'ref'")
    if backend in ("1password", "op"):
        if not shutil.which("op"):
            sys.exit("recall: 1Password CLI 'op' not found")
        proc = subprocess.run(["op", "read", ref], capture_output=True, text=True)
        if proc.returncode != 0:
            sys.exit(f"recall: op read failed: {proc.stderr.strip()}")
        return proc.stdout.rstrip("\n")
    if backend == "keychain":
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", ref, "-w"],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            sys.exit(f"recall: keychain lookup failed for {ref}")
        return proc.stdout.rstrip("\n")
    sys.exit(f"recall: unknown backend '{backend}'")


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_get(args, cfg) -> int:
    data = load_data(cfg)
    node = resolve(data, args.key)
    if node is None:
        print(f"recall: no such key '{args.key}'", file=sys.stderr)
        _suggest(data, args.key)
        return 1
    if not is_entry(node):
        # It's a namespace — list its children.
        _print_children(args.key, node)
        return 0
    kind = entry_kind(node)
    if kind in SECRET_KINDS:
        ref = node.get("ref", "(no ref)")
        print(f"{args.key} is a secret → {ref}")
        print(
            f"  run: recall secret {args.key}   (opens it in 1Password to copy by hand)"
        )
        return 0
    value = entry_value(node)
    if value is None:
        print(f"recall: entry '{args.key}' has no value", file=sys.stderr)
        return 1
    value = str(value)
    if args.show:
        print(value)
    else:
        to_clipboard(value)
        print(f"copied {args.key} ({kind}) to clipboard")
    audit("get", args.key)
    return 0


def cmd_secret(args, cfg) -> int:
    data = load_data(cfg)
    node = resolve(data, args.key)
    if node is None or not is_entry(node):
        print(f"recall: no such secret '{args.key}'", file=sys.stderr)
        return 1
    if entry_kind(node) not in SECRET_KINDS:
        print(
            f"recall: '{args.key}' is not a secret (use: recall {args.key})",
            file=sys.stderr,
        )
        return 1

    # Default: open the item in the vault app and let the human copy it. The
    # secret value never passes through recall — the strongest agent boundary.
    if not (args.copy or args.show):
        audit("secret-open", args.key)
        return open_in_vault(node, cfg, args.key)

    # Opt-in: resolve the value via the vault CLI (for scripting / piping).
    value = vault_read(node, cfg)
    audit("secret-copy", args.key)
    if args.show:
        print(value)
    else:
        secs = cfg.get("clipboard_clear_seconds", 45)
        to_clipboard(value, clear_after=secs)
        print(f"copied {args.key} to clipboard (clears in {secs}s)")
    return 0


def open_in_vault(entry: dict, cfg: dict, key: str) -> int:
    """Open the entry in its vault app for manual copy (no value touches recall)."""
    backend = entry.get("backend", cfg.get("default_backend", "1password"))
    ref = entry.get("ref")
    if backend in ("1password", "op"):
        if not ref:
            print("recall: secret entry has no 'ref'", file=sys.stderr)
            return 1
        link = onepassword_deeplink(ref)
        if link:
            subprocess.run(["open", link], check=False)
            print(f"opened {key} in 1Password — copy the secret manually")
        else:
            subprocess.run(["open", "onepassword://"], check=False)
            print(f"opened 1Password — find: {ref}")
        return 0
    if backend == "keychain":
        print(
            f"recall: keychain secrets can't be opened in an app — use: recall secret {key} --copy",
            file=sys.stderr,
        )
        return 1
    print(f"recall: don't know how to open backend '{backend}'", file=sys.stderr)
    return 1


def onepassword_deeplink(ref: str) -> str | None:
    """Build a onepassword://view-item deep link from an op:// reference.

    Resolves vault/item UUIDs via `op`. Returns None if they can't be resolved
    (caller then just launches the app). Secret field values present in the op
    response are never read or printed — only the item/vault/account IDs.
    """
    body = ref[len("op://") :] if ref.startswith("op://") else ref
    parts = body.split("/")
    if len(parts) < 2 or not shutil.which("op"):
        return None
    vault, item = parts[0], parts[1]
    try:
        meta = json.loads(
            subprocess.run(
                ["op", "item", "get", item, "--vault", vault, "--format", "json"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        item_id = meta.get("id")
        vault_id = (meta.get("vault") or {}).get("id")
        who = json.loads(
            subprocess.run(
                ["op", "whoami", "--format", "json"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        account = who.get("account_uuid")
        if not (item_id and vault_id):
            return None
        link = f"onepassword://view-item/?v={vault_id}&i={item_id}"
        if account:
            link += f"&a={account}"
        return link
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
        return None


def cmd_open(args, cfg) -> int:
    data = load_data(cfg)
    node = resolve(data, args.key)
    if not is_entry(node):
        print(f"recall: no such entry '{args.key}'", file=sys.stderr)
        return 1
    if entry_kind(node) in SECRET_KINDS:
        print("recall: refusing to open a secret", file=sys.stderr)
        return 1
    value = entry_value(node)
    if not value:
        print(f"recall: '{args.key}' has no value to open", file=sys.stderr)
        return 1
    subprocess.run(["open", str(value)], check=False)
    audit("open", args.key)
    return 0


def cmd_search(args, cfg) -> int:
    data = load_data(cfg)
    q = args.query.lower()
    hits = []
    for key, entry in walk_entries(data):
        note = one_line(entry.get("note", ""))
        tags = " ".join(entry_tags(entry))
        kind = entry_kind(entry)
        # Match on key/note/tags. Match non-secret values too, but never print them.
        haystack = f"{key} {note} {tags}".lower()
        if kind not in SECRET_KINDS:
            haystack += " " + str(entry.get("value", "")).lower()
        if q in haystack:
            hits.append((key, kind, note))
    if not hits:
        print(f"recall: no matches for '{args.query}'")
        return 1
    for key, kind, note in sorted(hits):
        line = f"  {key}  [{kind}]"
        if note:
            line += f"  — {note}"
        print(line)
    return 0


def cmd_list(args, cfg) -> int:
    data = load_data(cfg)
    root = data
    if args.prefix:
        root = resolve(data, args.prefix)
        if root is None:
            print(f"recall: no such namespace '{args.prefix}'", file=sys.stderr)
            return 1
        if is_entry(root):
            kind = entry_kind(root)
            marker = "🔒" if kind in SECRET_KINDS else "  "
            line = f"{marker} {args.prefix}  [{kind}]"
            note = one_line(root.get("note", ""))
            if note:
                line += f"  — {note}"
            print(line)
            return 0
    for key, entry in sorted(walk_entries(root, args.prefix or "")):
        kind = entry_kind(entry)
        marker = "🔒" if kind in SECRET_KINDS else "  "
        line = f"{marker} {key}  [{kind}]"
        note = one_line(entry.get("note", ""))
        if note:
            line += f"  — {note}"
        print(line)
    return 0


def cmd_tags(args, cfg) -> int:
    data = load_data(cfg)
    want = args.tag.lower()
    found = False
    for key, entry in sorted(walk_entries(data)):
        tags = [tag.lower() for tag in entry_tags(entry)]
        if want in tags:
            found = True
            line = f"  {key}  [{entry_kind(entry)}]"
            note = one_line(entry.get("note", ""))
            if note:
                line += f"  — {note}"
            print(line)
    if not found:
        print(f"recall: no entries tagged '{args.tag}'")
        return 1
    return 0


def cmd_json(args, cfg) -> int:
    data = load_data(cfg)
    node = data if not args.key else resolve(data, args.key)
    if node is None:
        print(f"recall: no such key '{args.key}'", file=sys.stderr)
        return 1
    print(json.dumps(node, indent=2, ensure_ascii=False, default=str))
    return 0


def cmd_doctor(args, cfg) -> int:
    problems = 0
    fp = data_path(cfg)
    print(f"data file  : {fp}  {'✓' if fp.exists() else '✗ MISSING'}")
    print(f"config dir : {config_dir()}")
    print(
        f"op CLI     : {'✓ ' + (shutil.which('op') or '') if shutil.which('op') else '✗ not installed'}"
    )
    if not fp.exists():
        return 1
    data = load_data(cfg)
    n = 0
    for key, entry in walk_entries(data):
        n += 1
        kind = entry_kind(entry)
        if kind in SECRET_KINDS:
            if not entry.get("ref"):
                print(f"  ✗ {key}: secret without 'ref'")
                problems += 1
        elif entry.get("value") in (None, ""):
            print(f"  ✗ {key}: {kind} without 'value'")
            problems += 1
        if "tags" in entry and not isinstance(entry.get("tags"), list):
            print(f"  ✗ {key}: tags must be a list")
            problems += 1
    print(f"entries    : {n} ({problems} problem(s))")
    return 1 if problems else 0


# --------------------------------------------------------------------------- #
# Display helpers
# --------------------------------------------------------------------------- #
def _print_children(prefix: str, node: dict) -> None:
    print(f"{prefix}/  (namespace)")
    for key, child in sorted(node.items()):
        kind = entry_kind(child) if is_entry(child) else "namespace"
        line = f"  {prefix}.{key}  [{kind}]"
        if is_entry(child):
            note = one_line(child.get("note", ""))
            if note:
                line += f"  — {note}"
        print(line)


def _suggest(data: dict, key: str) -> None:
    leaf = key.split(".")[-1].lower()
    near = [k for k, _ in walk_entries(data) if leaf in k.lower()]
    if near:
        print("  did you mean:", ", ".join(sorted(near)[:5]), file=sys.stderr)


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #
SUBCOMMANDS = {
    "get",
    "secret",
    "open",
    "search",
    "list",
    "tags",
    "json",
    "doctor",
    "export",
    "help",
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="recall", description="A small data jar for data you fetch often."
    )
    p.add_argument("--version", action="version", version=f"recall {__version__}")
    sub = p.add_subparsers(dest="command")

    g = sub.add_parser("get", help="copy a non-secret value to the clipboard")
    g.add_argument("key")
    g.add_argument("--show", action="store_true", help="print value instead of copying")
    g.set_defaults(func=cmd_get)

    s = sub.add_parser(
        "secret", help="open a secret in 1Password (or --copy to clipboard)"
    )
    s.add_argument("key")
    s.add_argument(
        "--copy",
        action="store_true",
        help="resolve via the vault CLI and copy to clipboard",
    )
    s.add_argument(
        "--show", action="store_true", help="resolve and print the value (discouraged)"
    )
    s.set_defaults(func=cmd_secret)

    o = sub.add_parser("open", help="open a url entry in the browser")
    o.add_argument("key")
    o.set_defaults(func=cmd_open)

    se = sub.add_parser("search", help="search keys, notes and tags")
    se.add_argument("query")
    se.set_defaults(func=cmd_search)

    li = sub.add_parser("list", help="list entries under a namespace")
    li.add_argument("prefix", nargs="?", default="")
    li.set_defaults(func=cmd_list)

    tg = sub.add_parser("tags", help="list entries with a tag")
    tg.add_argument("tag")
    tg.set_defaults(func=cmd_tags)

    js = sub.add_parser("json", help="dump a subtree as JSON")
    js.add_argument("key", nargs="?", default="")
    js.set_defaults(func=cmd_json)

    dr = sub.add_parser("doctor", help="validate the data file and environment")
    dr.set_defaults(func=cmd_doctor)

    ex = sub.add_parser("export", help="alias for: json (whole tree)")
    ex.set_defaults(func=lambda a, c: cmd_json(argparse.Namespace(key=""), c))

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cfg = load_config()
    # Bare `recall <key>` → treat as `get <key>` when the first token is not a subcommand.
    if argv and argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        argv = ["get"] + argv
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return args.func(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
