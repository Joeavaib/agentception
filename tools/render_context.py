#!/usr/bin/env python3
"""Deterministischer Prefix-Renderer (s02-prefix-renderer, static-first).

Regeln (AGENTS.md R2/R3/R6):
- Ordnung fix: sys > tools > policy > filemap > task > query
- LF-only, UTF-8 ohne BOM, keine Timestamps im Prefix
- dict-Keys sortiert (json.dumps sort_keys=True), Listen mit
  Skalaren sortiert, stabile Delimiter ``=== CTX:<LAYER>:v1:... ===``
- Switch nur als Suffix-Append `` [SWITCH:v1:<target>]``

Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json

LAYER_ORDER = ("sys", "tools", "policy", "filemap", "task", "query")
SWITCH_SUFFIX_TEMPLATE = " [SWITCH:v1:{target}]"
DEFAULT_SWITCH_TARGET = "codex"


def _norm_lf(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _canonicalize(obj):
    if isinstance(obj, dict):
        return {k: _canonicalize(obj[k]) for k in sorted(obj.keys())}
    if isinstance(obj, (list, tuple)):
        items = [_canonicalize(v) for v in obj]
        if all(isinstance(v, (str, int, float, bool)) or v is None for v in items):
            try:
                return sorted(items, key=lambda v: (str(type(v).__name__), str(v)))
            except TypeError:
                return items
        return items
    return obj


def _render_body(value) -> str:
    if isinstance(value, str):
        return _norm_lf(value).strip("\n")
    canonical = _canonicalize(value)
    return json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def render_prefix(facts: dict, switch: str | bool | None = None) -> str:
    """Rendere kanonischen Prefix aus facts. Switch nur als Suffix."""
    parts: list[str] = []
    for layer in LAYER_ORDER:
        if layer not in facts:
            continue
        upper = layer.upper()
        body = _render_body(facts[layer])
        parts.append(f"=== CTX:{upper}:v1:START ===\n{body}\n=== CTX:{upper}:v1:END ===")
    out = "\n".join(parts) + "\n" if parts else "\n"
    out = _norm_lf(out)
    if switch:
        target = DEFAULT_SWITCH_TARGET if switch is True else str(switch)
        out = out.rstrip("\n") + SWITCH_SUFFIX_TEMPLATE.format(target=target) + "\n"
    return out


def canonical_bytes(prefix: str) -> bytes:
    return _norm_lf(prefix).encode("utf-8")


def sha256_hex(prefix: str) -> str:
    return hashlib.sha256(canonical_bytes(prefix)).hexdigest()


GOLDEN_FACTS = {
    "sys": "core-v1 static-first",
    "tools": {"b": "pytest", "a": "render"},
    "policy": ["verify-first", "static-first"],
    "filemap": {"z.py": "m", "a.py": "n"},
    "task": {"title": "renderer", "id": "s02"},
    "query": "stabil?",
}

# Wird nach Erst-Render auf den deterministischen Wert gesetzt (Golden-Hash).
GOLDEN_SHA = "5bb192f6cf0800305cc407e01afd391ebcf3c30d7f20146f537275ad6e2fc130"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Deterministischer Prefix-Renderer")
    ap.add_argument("--golden", action="store_true", help="Goldene Fakten rendern")
    ap.add_argument("--switch", nargs="?", const=DEFAULT_SWITCH_TARGET, default=None,
                    help="Switch-Suffix appenden (default: codex)")
    ap.add_argument("--check", action="store_true", help="Golden-Hash gegen GOLDEN_SHA pruefen")
    args = ap.parse_args(argv)
    prefix = render_prefix(GOLDEN_FACTS, switch=args.switch) if args.golden or args.switch else render_prefix(GOLDEN_FACTS)
    if args.check:
        digest = sha256_hex(render_prefix(GOLDEN_FACTS))
        if GOLDEN_SHA == "PLACEHOLDER":
            print(f"GOLDEN_SHA not set, current={digest}")
            return 2
        if digest != GOLDEN_SHA:
            print(f"GOLDEN mismatch: got={digest} want={GOLDEN_SHA}")
            return 1
        print(f"GOLDEN ok: {digest}")
        return 0
    import sys
    sys.stdout.write(prefix)
    sys.stdout.write(f"---\nsha256: {sha256_hex(prefix)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
