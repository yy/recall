"""recall — a small CLI "data jar" for the facts you fetch over and over.

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

Data model (``facts.yaml``)::

    orcid:
      kind: id
      value: "0000-0000-0000-0000"
    uva:
      irb:
        kind: url
        value: https://...
        note: Use NetBadge
    github:
      kind: secret
      backend: 1password
      ref: op://Private/GitHub/token

A mapping with a ``kind:`` field is an *entry*; one without is a *namespace*.
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


def facts_path(cfg: dict) -> Path:
    """Resolution order: $RECALL_FILE > config.yaml 'facts_file' > config dir default.

    The facts file does not have to live in the config dir — config.yaml just
    points at wherever it actually is (e.g. a private dotfiles repo).
    """
    if env := os.environ.get("RECALL_FILE"):
        return Path(env).expanduser()
    if cfg.get("facts_file"):
        return Path(str(cfg["facts_file"])).expanduser()
    return config_dir() / "facts.yaml"


def load_config() -> dict:
    path = config_dir() / "config.yaml"
    cfg = dict(DEFAULT_CONFIG)
    if path.exists():
        loaded = yaml.safe_load(path.read_text()) or {}
        cfg.update(loaded)
    return cfg


def load_facts(cfg: dict) -> dict:
    path = facts_path(cfg)
    if not path.exists():
        sys.exit(
            f"recall: no facts file at {path}\n"
            f"point config.yaml 'facts_file' at it, set RECALL_FILE, or see 'recall doctor'."
        )
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        sys.exit(f"recall: {path} must be a YAML mapping at the top level")
    return data


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
    data = load_facts(cfg)
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
        print(f"  run: recall secret {args.key}")
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
    data = load_facts(cfg)
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
    value = vault_read(node, cfg)
    audit("secret", args.key)
    if args.show:
        print(value)
    else:
        to_clipboard(value, clear_after=cfg.get("clipboard_clear_seconds", 45))
        secs = cfg.get("clipboard_clear_seconds", 45)
        print(f"copied {args.key} to clipboard (clears in {secs}s)")
    return 0


def cmd_open(args, cfg) -> int:
    data = load_facts(cfg)
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
    data = load_facts(cfg)
    q = args.query.lower()
    hits = []
    for key, entry in walk_entries(data):
        note = str(entry.get("note", ""))
        tags = " ".join(entry.get("tags", []) or [])
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
    data = load_facts(cfg)
    root = data
    if args.prefix:
        root = resolve(data, args.prefix)
        if root is None:
            print(f"recall: no such namespace '{args.prefix}'", file=sys.stderr)
            return 1
        if is_entry(root):
            _print_children(args.prefix, {})
            return 0
    for key, entry in sorted(walk_entries(root, args.prefix or "")):
        kind = entry_kind(entry)
        marker = "🔒" if kind in SECRET_KINDS else "  "
        print(f"{marker} {key}  [{kind}]")
    return 0


def cmd_tags(args, cfg) -> int:
    data = load_facts(cfg)
    want = args.tag.lower()
    found = False
    for key, entry in sorted(walk_entries(data)):
        tags = [str(t).lower() for t in (entry.get("tags") or [])]
        if want in tags:
            found = True
            print(f"  {key}  [{entry_kind(entry)}]")
    if not found:
        print(f"recall: no entries tagged '{args.tag}'")
        return 1
    return 0


def cmd_json(args, cfg) -> int:
    data = load_facts(cfg)
    node = data if not args.key else resolve(data, args.key)
    if node is None:
        print(f"recall: no such key '{args.key}'", file=sys.stderr)
        return 1
    print(json.dumps(node, indent=2, ensure_ascii=False, default=str))
    return 0


def cmd_doctor(args, cfg) -> int:
    problems = 0
    fp = facts_path(cfg)
    print(f"facts file : {fp}  {'✓' if fp.exists() else '✗ MISSING'}")
    print(f"config dir : {config_dir()}")
    print(
        f"op CLI     : {'✓ ' + (shutil.which('op') or '') if shutil.which('op') else '✗ not installed'}"
    )
    if not fp.exists():
        return 1
    data = load_facts(cfg)
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
    print(f"entries    : {n} ({problems} problem(s))")
    return 1 if problems else 0


# --------------------------------------------------------------------------- #
# Display helpers
# --------------------------------------------------------------------------- #
def _print_children(prefix: str, node: dict) -> None:
    print(f"{prefix}/  (namespace)")
    for key, child in sorted(node.items()):
        kind = entry_kind(child) if is_entry(child) else "namespace"
        print(f"  {prefix}.{key}  [{kind}]")


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
        prog="recall", description="A small data jar for facts you fetch often."
    )
    p.add_argument("--version", action="version", version=f"recall {__version__}")
    sub = p.add_subparsers(dest="command")

    g = sub.add_parser("get", help="copy a non-secret value to the clipboard")
    g.add_argument("key")
    g.add_argument("--show", action="store_true", help="print value instead of copying")
    g.set_defaults(func=cmd_get)

    s = sub.add_parser("secret", help="resolve a secret reference via the vault")
    s.add_argument("key")
    s.add_argument("--show", action="store_true", help="print value instead of copying")
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

    dr = sub.add_parser("doctor", help="validate the facts file and environment")
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
