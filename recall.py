"""recall — a small CLI "data jar" for lookup data you fetch over and over.

Two tiers, by threat model:

  * non-secrets (URLs, IDs, account numbers, ORCID, reusable snippets) live in
    a plain JSONL file and are returned directly;
  * secrets (API keys, tokens, passwords) are NEVER stored here — only a
    reference to a vault (e.g. ``op://Private/GitHub/token``) is stored, and the
    value is resolved on demand via ``recall secret``.

The bare ``recall <key>`` form copies a non-secret value to the clipboard. It
will not resolve a secret: it prints the reference and tells you to use
``recall secret``. That split is the whole security model — an agent can be
allowed ``recall``/``search``/``list`` freely while ``recall secret`` stays
gated.

Data model (``data.jsonl``): one JSON object per line, with a ``key`` field::

    {"key": "orcid.self", "kind": "id", "value": "0000-0000-0000-0000", "note": "My ORCID iD"}
    {"key": "github.token", "kind": "secret", "backend": "1password", "ref": "op://Private/GitHub/token"}
    {"key": "email.reply-template", "kind": "file", "value": "~/recall/snippets/reply.md"}

Store multiline content in files and point at them with ``kind`` set to ``file``.
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

__version__ = "0.2.0"

SECRET_KINDS = {"secret"}
SUPPORTED_SECRET_BACKENDS = {"1password", "keychain", "op"}
# A node is an entry if it is a mapping carrying one of these marker fields.
ENTRY_MARKERS = ("kind", "value", "ref")

DEFAULT_CONFIG = {
    "clipboard_clear_seconds": 45,
    "default_backend": "1password",
}

STARTER_DATA = (
    '{"key": "orcid.self", "kind": "id", "value": "0000-0000-0000-0000", '
    '"note": "My ORCID iD", "tags": ["identity"]}\n'
    '{"key": "github.token", "kind": "secret", "backend": "1password", '
    '"ref": "op://Private/GitHub/token", "note": "GitHub token", "tags": ["dev"]}\n'
)


# --------------------------------------------------------------------------- #
# Paths & loading
# --------------------------------------------------------------------------- #
def config_dir() -> Path:
    if env := os.environ.get("RECALL_DIR"):
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME", "~/.config")
    return Path(base).expanduser() / "recall"


def config_path() -> Path:
    return config_dir() / "config.json"


def data_path(cfg: dict) -> Path:
    """Find the JSONL data file.

    The data file does not have to live in the config dir; config.json just
    points at wherever it actually is (e.g. a private dotfiles repo).
    """
    if env := os.environ.get("RECALL_DATA_FILE"):
        return Path(env).expanduser()
    if cfg.get("data_file"):
        return resolve_config_data_path(str(cfg["data_file"]))
    return config_dir() / "data.jsonl"


def resolve_config_data_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return config_dir() / path


def load_config() -> dict:
    path = config_path()
    cfg = dict(DEFAULT_CONFIG)
    if path.exists():
        loaded = load_json_object_file(path, label="config file")
        validate_config(loaded, path)
        cfg.update(loaded)
    return cfg


def load_config_for_doctor() -> tuple[dict[str, Any], str | None]:
    """Load config without aborting so `doctor` can report config problems."""
    path = config_path()
    cfg = dict(DEFAULT_CONFIG)
    if not path.exists():
        return cfg, None
    try:
        loaded = load_json_object_file(path, label="config file")
        validate_config(loaded, path)
    except SystemExit as exc:
        return cfg, str(exc)
    cfg.update(loaded)
    return cfg, None


def validate_config(cfg: dict[str, Any], path: Path) -> None:
    data_file = cfg.get("data_file")
    if data_file is not None and not isinstance(data_file, str):
        sys.exit(f"recall: config file {path} field 'data_file' must be a string")

    default_backend = cfg.get("default_backend")
    if default_backend is not None and not isinstance(default_backend, str):
        sys.exit(f"recall: config file {path} field 'default_backend' must be a string")
    if default_backend is not None:
        validate_backend_name(
            default_backend, path=path, label="config file", field="default_backend"
        )

    clear_after = cfg.get("clipboard_clear_seconds")
    if clear_after is None:
        return
    if isinstance(clear_after, bool) or not isinstance(clear_after, int):
        sys.exit(
            f"recall: config file {path} field 'clipboard_clear_seconds' must be an integer"
        )
    if clear_after < 0:
        sys.exit(
            f"recall: config file {path} field 'clipboard_clear_seconds' must be non-negative"
        )


def load_data(cfg: dict) -> dict:
    path = data_path(cfg)
    if not path.exists():
        sys.exit(
            f"recall: no data file at {path}\n"
            f"point config.json 'data_file' at it, set RECALL_DATA_FILE, or see 'recall doctor'."
        )
    numbered_entries = load_jsonl_entries(path)
    line_numbers = [line_number for line_number, _ in numbered_entries]
    entries = [entry for _, entry in numbered_entries]
    return normalize_data(entries, path, line_numbers=line_numbers)


def load_json_object_file(path: Path, *, label: str) -> dict[str, Any]:
    try:
        text = path.read_text()
    except OSError as exc:
        detail = exc.strerror or str(exc)
        sys.exit(f"recall: can't read {label} {path}: {detail}")
    except UnicodeDecodeError:
        sys.exit(f"recall: {label} {path} must be valid UTF-8 text")
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        sys.exit(
            f"recall: invalid JSON in {label} {path} "
            f"at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        )
    if not isinstance(loaded, dict):
        sys.exit(f"recall: {label} {path} must be a JSON object")
    return loaded


def load_jsonl_entries(path: Path) -> list[tuple[int, dict[str, Any]]]:
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        detail = exc.strerror or str(exc)
        sys.exit(f"recall: can't read data file {path}: {detail}")
    except UnicodeDecodeError:
        sys.exit(f"recall: data file {path} must be valid UTF-8 text")
    entries: list[tuple[int, dict[str, Any]]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.exit(
                f"recall: invalid JSONL in {path} at line {line_number}, "
                f"column {exc.colno}: {exc.msg}"
            )
        if not isinstance(loaded, dict):
            sys.exit(f"recall: {path}: line {line_number} must be a JSON object")
        entries.append((line_number, loaded))
    return entries


def normalize_data(
    records: list[dict[str, Any]], path: Path, *, line_numbers: list[int] | None = None
) -> dict:
    """Convert JSONL records to the internal namespace tree."""
    root: dict[str, Any] = {}
    if line_numbers is None:
        line_numbers = list(range(1, len(records) + 1))
    elif len(line_numbers) != len(records):
        raise ValueError("line_numbers length must match records length")
    for line_number, record in zip(line_numbers, records):
        key = record.get("key")
        if not isinstance(key, str):
            sys.exit(f"recall: {path}: line {line_number} must have string field 'key'")
        parts = key.split(".")
        if any(not part for part in parts):
            sys.exit(f"recall: {path}: invalid empty key segment in '{key}'")
        entry = dict(record)
        entry.pop("key", None)
        if not is_entry(entry):
            sys.exit(
                f"recall: {path}: line {line_number} entry '{key}' must include "
                "'kind', 'value', or 'ref'"
            )
        insert_entry(root, parts, entry, key, path)
    validate_tree(root, "", path)
    return root


def flatten_entries(data: dict) -> list[dict[str, Any]]:
    # Preserve the file's own order (entries grouped under each namespace in
    # first-seen order) rather than re-sorting, so `format` keeps the author's
    # curated grouping. walk_entries yields in tree-insertion order.
    records = []
    for key, entry in walk_entries(data):
        record = {"key": key}
        record.update(entry)
        records.append(record)
    return records


CANONICAL_RECORD_FIELDS = ("key", "kind", "value", "backend", "ref", "note", "tags")


def canonicalize_record(record: dict[str, Any]) -> dict[str, Any]:
    ordered: dict[str, Any] = {}
    for field in CANONICAL_RECORD_FIELDS:
        if field in record:
            ordered[field] = record[field]
    for field in sorted(record):
        if field not in ordered:
            ordered[field] = record[field]
    return ordered


def format_jsonl(records: list[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(canonicalize_record(record), ensure_ascii=False) + "\n"
        for record in records
    )


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
        validate_entry(node, dotted, path)
        return
    if not isinstance(node, dict):
        label = dotted or "<root>"
        sys.exit(
            f"recall: {path}: '{label}' is neither an entry mapping nor a namespace"
        )
    for key, child in node.items():
        child_path = f"{dotted}.{key}" if dotted else str(key)
        validate_tree(child, child_path, path)


def validate_entry(entry: dict, dotted: str, path: Path) -> None:
    label = dotted or "<entry>"
    kind = entry.get("kind")
    if not isinstance(kind, str):
        sys.exit(f"recall: {path}: '{label}' field 'kind' must be a string")
    for field in ("value", "backend", "ref", "note"):
        value = entry.get(field)
        if value is not None and not isinstance(value, str):
            sys.exit(f"recall: {path}: '{label}' field '{field}' must be a string")
    for field in ("kind", "value", "backend", "ref", "note"):
        value = entry.get(field)
        if isinstance(value, str) and "\n" in value:
            sys.exit(
                f"recall: {path}: '{label}' field '{field}' must be one line; "
                "store multiline content in a file and use a file entry"
            )
    backend = entry.get("backend")
    if backend is not None:
        if not isinstance(backend, str):
            sys.exit(f"recall: {path}: '{label}' field 'backend' must be a string")
        validate_backend_name(
            backend, path=path, label=f"entry '{label}'", field="backend"
        )
    if kind in SECRET_KINDS:
        if not entry.get("ref"):
            sys.exit(f"recall: {path}: '{label}' secret entries must include 'ref'")
    elif entry.get("value") in (None, ""):
        sys.exit(f"recall: {path}: '{label}' non-secret entries must include 'value'")
    tags = entry.get("tags")
    if tags is not None and not isinstance(tags, list):
        sys.exit(f"recall: {path}: '{label}' field 'tags' must be a list")
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, str):
                sys.exit(f"recall: {path}: '{label}' tags must be one-line strings")
            if "\n" in tag:
                sys.exit(f"recall: {path}: '{label}' tags must be one-line strings")


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


def runtime_entry_value(entry: dict, cfg: dict) -> str | None:
    value = entry_value(entry)
    if value is None:
        return None
    if entry_kind(entry) != "file":
        return str(value)

    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return str(path)
    return str(data_path(cfg).parent / path)


def entry_backend(entry: dict, cfg: dict) -> str:
    return str(entry.get("backend", cfg.get("default_backend", "1password")))


def secret_usage_hint(key: str, entry: dict, cfg: dict) -> str:
    backend = entry_backend(entry, cfg)
    if backend == "keychain":
        return f"  run: recall secret {key} --copy   (resolves it via Keychain and copies it)"
    return f"  run: recall secret {key}   (opens it in 1Password to copy by hand)"


def one_line(text: Any) -> str:
    return " ".join(str(text).split())


def validate_backend_name(backend: str, *, path: Path, label: str, field: str) -> None:
    if backend in SUPPORTED_SECRET_BACKENDS:
        return
    choices = ", ".join(sorted(SUPPORTED_SECRET_BACKENDS))
    sys.exit(f"recall: {label} {path} field '{field}' must be one of: {choices}")


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
        proc = subprocess.Popen(
            ["sh", "-c", script],
            stdin=subprocess.PIPE,
            start_new_session=True,
        )
        if proc.stdin is not None:
            proc.stdin.write(text.encode())
            proc.stdin.close()


def audit(command: str, key: str) -> None:
    path = config_dir() / "audit.log"
    stamp = _dt.datetime.now().isoformat(timespec="seconds")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(f"{stamp}\t{command}\t{key}\n")
    except OSError:
        pass  # never let audit failure block a lookup


def vault_read(entry: dict, cfg: dict) -> str:
    backend = entry_backend(entry, cfg)
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
# Init helpers
# --------------------------------------------------------------------------- #
def prompt_value(label: str, default: str) -> str:
    response = input(f"{label} [{default}]: ").strip()
    return response or default


def prompt_yes_no(label: str, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    response = input(f"{label} [{suffix}]: ").strip().lower()
    if not response:
        return default
    return response in {"y", "yes"}


def write_text_file(path: Path, text: str, force: bool = False) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return True


def validate_init_write_target(path: Path, *, label: str) -> str | None:
    if path.exists() and not path.is_file():
        return f"recall: {label} path must be a file: {path}"
    if path.parent.exists() and not path.parent.is_dir():
        return f"recall: can't create {label} {path}: parent path is not a directory"
    return None


def build_config_text(
    data_file: str, clipboard_clear_seconds: int, default_backend: str
) -> str:
    return (
        json.dumps(
            {
                "data_file": data_file,
                "clipboard_clear_seconds": clipboard_clear_seconds,
                "default_backend": default_backend,
            },
            indent=2,
        )
        + "\n"
    )


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_init(args, cfg) -> int:
    default_data_file = str(config_dir() / "data.jsonl")
    interactive = not args.yes

    data_file = args.data_file
    if not data_file and interactive:
        data_file = prompt_value(
            "Where should recall store data.jsonl?", default_data_file
        )
    data_file = data_file or default_data_file

    clear_seconds = args.clipboard_clear_seconds
    if clear_seconds is None and interactive:
        raw = prompt_value(
            "Seconds before copied secrets are cleared",
            str(DEFAULT_CONFIG["clipboard_clear_seconds"]),
        )
        try:
            clear_seconds = int(raw)
        except ValueError:
            print("recall: clipboard clear seconds must be an integer", file=sys.stderr)
            return 1
    if clear_seconds is None:
        clear_seconds = int(DEFAULT_CONFIG["clipboard_clear_seconds"])
    if clear_seconds < 0:
        print("recall: clipboard clear seconds must be non-negative", file=sys.stderr)
        return 1

    backend = args.default_backend
    if not backend and interactive:
        backend = prompt_value(
            "Default secret backend", str(DEFAULT_CONFIG["default_backend"])
        )
    backend = backend or str(DEFAULT_CONFIG["default_backend"])
    if backend not in SUPPORTED_SECRET_BACKENDS:
        choices = ", ".join(sorted(SUPPORTED_SECRET_BACKENDS))
        print(f"recall: default backend must be one of: {choices}", file=sys.stderr)
        return 1

    sample = args.sample
    if sample is None and interactive:
        sample = prompt_yes_no("Create a starter data file?", True)
    sample = True if sample is None else sample

    cfg_path = config_path()
    data_path_for_write = resolve_config_data_path(data_file)

    for label, path in (
        ("config file", cfg_path),
        ("data file", data_path_for_write),
    ):
        if error := validate_init_write_target(path, label=label):
            print(error, file=sys.stderr)
            return 1

    if cfg_path.exists() and not args.force:
        if interactive and prompt_yes_no(f"{cfg_path} exists. Overwrite it?", False):
            overwrite_config = True
        else:
            print(
                f"recall: config already exists at {cfg_path} (use --force)",
                file=sys.stderr,
            )
            return 1
    else:
        overwrite_config = True

    config_text = build_config_text(data_file, clear_seconds, backend)
    write_text_file(cfg_path, config_text, force=overwrite_config)
    print(f"wrote config: {cfg_path}")

    if data_path_for_write.exists():
        print(f"data file already exists: {data_path_for_write}")
    else:
        text = STARTER_DATA if sample else ""
        write_text_file(data_path_for_write, text, force=False)
        print(f"created data file: {data_path_for_write}")

    print("\nNext steps:")
    print(f"  edit {data_path_for_write}")
    print("  run: recall doctor")
    return 0


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
        print(secret_usage_hint(args.key, node, cfg))
        return 0
    value = runtime_entry_value(node, cfg)
    if value is None:
        print(f"recall: entry '{args.key}' has no value", file=sys.stderr)
        return 1
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
    if not args.copy:
        status = open_in_vault(node, cfg, args.key)
        if status == 0:
            audit("secret-open", args.key)
        return status

    # Opt-in: resolve the value via the vault CLI (for scripting / piping).
    value = vault_read(node, cfg)
    secs = cfg.get("clipboard_clear_seconds", 45)
    to_clipboard(value, clear_after=secs)
    audit("secret-copy", args.key)
    if secs and secs > 0:
        print(f"copied {args.key} to clipboard (clears in {secs}s)")
    else:
        print(f"copied {args.key} to clipboard (auto-clear disabled)")
    return 0


def open_in_vault(entry: dict, cfg: dict, key: str) -> int:
    """Open the entry in its vault app for manual copy (no value touches recall)."""
    backend = entry_backend(entry, cfg)
    ref = entry.get("ref")
    if backend in ("1password", "op"):
        if not ref:
            print("recall: secret entry has no 'ref'", file=sys.stderr)
            return 1
        link = onepassword_deeplink(ref)
        if link:
            result = subprocess.run(["open", link], check=False)
            if result.returncode == 0:
                print(f"opened {key} in 1Password — copy the secret manually")
                return 0
            print(f"recall: failed to open 1Password item for '{key}'", file=sys.stderr)
            return 1

        result = subprocess.run(["open", "onepassword://"], check=False)
        if result.returncode == 0:
            print(f"opened 1Password — find: {ref}")
            return 0
        print("recall: failed to open 1Password", file=sys.stderr)
        return 1
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
    except (
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        KeyError,
        AttributeError,
    ):
        return None


def cmd_open(args, cfg) -> int:
    data = load_data(cfg)
    node = resolve(data, args.key)
    if not is_entry(node):
        print(f"recall: no such entry '{args.key}'", file=sys.stderr)
        return 1
    kind = entry_kind(node)
    if kind in SECRET_KINDS:
        print("recall: refusing to open a secret", file=sys.stderr)
        return 1
    if kind not in {"url", "file"}:
        print(
            f"recall: '{args.key}' is a {kind}, not something to open", file=sys.stderr
        )
        return 1
    target = runtime_entry_value(node, cfg)
    if target is None:
        print(f"recall: '{args.key}' has no value to open", file=sys.stderr)
        return 1
    result = subprocess.run(["open", target], check=False)
    if result.returncode != 0:
        print(f"recall: failed to open '{args.key}'", file=sys.stderr)
        return 1
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


def cmd_format(args, cfg) -> int:
    data = load_data(cfg)
    formatted = format_jsonl(flatten_entries(data))
    if args.check:
        if data_path(cfg).read_text() != formatted:
            print(
                f"recall: data file is not in canonical format: {data_path(cfg)}",
                file=sys.stderr,
            )
            return 1
        return 0
    sys.stdout.write(formatted)
    return 0


def cmd_doctor(args, cfg) -> int:
    # `main()` calls doctor with `{}` so it can validate config.json itself.
    # Tests and library-style callers may pass an explicit config; honor that
    # instead of reaching back into the user's global recall directory.
    if cfg:
        config_error = None
    else:
        cfg, config_error = load_config_for_doctor()
    cfg_path = config_path()
    if config_error:
        print(f"config file: {cfg_path}  ✗ INVALID")
        print(f"  {config_error}")
    else:
        status = "✓" if cfg_path.exists() else "✗ MISSING"
        print(f"config file: {cfg_path}  {status}")
    fp = data_path(cfg)
    print(f"config dir : {config_dir()}")
    if config_error:
        return 1
    if not fp.exists():
        print(f"data file  : {fp}  ✗ MISSING")
        return 1
    try:
        data = load_data(cfg)
    except SystemExit as exc:
        print(f"data file  : {fp}  ✗ INVALID")
        print(f"  {exc}")
        return 1
    print(f"data file  : {fp}  ✓")
    backends = {str(cfg.get("default_backend", "1password"))}
    for _, entry in walk_entries(data):
        if entry_kind(entry) in SECRET_KINDS:
            backends.add(entry_backend(entry, cfg))
    if backends & {"1password", "op"}:
        op_path = shutil.which("op")
        print(f"op CLI     : {'✓ ' + op_path if op_path else '✗ not installed'}")
    if "keychain" in backends:
        security_path = shutil.which("security")
        print(
            f"security   : {'✓ ' + security_path if security_path else '✗ not installed'}"
        )
    n = sum(1 for _ in walk_entries(data))
    problems = 0
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
    "init",
    "get",
    "secret",
    "open",
    "search",
    "list",
    "tags",
    "json",
    "format",
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

    init = sub.add_parser("init", help="create recall config and data file")
    init.add_argument("--data-file", help="path to the data.jsonl file to use")
    init.add_argument(
        "--clipboard-clear-seconds",
        type=int,
        help="seconds before secrets copied with --copy are cleared",
    )
    init.add_argument(
        "--default-backend",
        default="",
        help="default secret backend for entries without backend",
    )
    sample = init.add_mutually_exclusive_group()
    sample.add_argument(
        "--sample",
        dest="sample",
        action="store_true",
        default=None,
        help="create starter entries in a new data file",
    )
    sample.add_argument(
        "--no-sample",
        dest="sample",
        action="store_false",
        help="create an empty data file",
    )
    init.add_argument(
        "--yes",
        action="store_true",
        help="accept defaults for omitted options without prompting",
    )
    init.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing config.json",
    )
    init.set_defaults(func=cmd_init)

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
    s.set_defaults(func=cmd_secret)

    o = sub.add_parser("open", help="open a url or file entry")
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

    fmt = sub.add_parser("format", help="emit the data file in canonical JSONL order")
    fmt.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when the data file is not already canonical",
    )
    fmt.set_defaults(func=cmd_format)

    dr = sub.add_parser("doctor", help="validate the data file and environment")
    dr.set_defaults(func=cmd_doctor)

    ex = sub.add_parser("export", help="alias for: json (whole tree)")
    ex.set_defaults(func=lambda a, c: cmd_json(argparse.Namespace(key=""), c))

    sub.add_parser("help", help="show this help message")

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Bare `recall <key>` → treat as `get <key>` when the first token is not a subcommand.
    if argv and argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        argv = ["get"] + argv
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None) or args.command == "help":
        parser.print_help()
        return 0
    cfg = {} if args.command in {"init", "doctor"} else load_config()
    return args.func(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
