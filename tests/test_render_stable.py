"""Golden-Hash-Test fuer s02-prefix-renderer (stdlib only)."""
import re

from tools.render_context import (
    GOLDEN_FACTS,
    GOLDEN_SHA,
    LAYER_ORDER,
    canonical_bytes,
    render_prefix,
    sha256_hex,
)


def _shuffled_facts(reverse: bool) -> dict:
    keys = list(GOLDEN_FACTS.keys())
    keys = keys[::-1] if reverse else keys
    facts = {}
    for k in keys:
        facts[k] = GOLDEN_FACTS[k]
    # unsortierte innere Keys einstreuen
    facts["tools"] = {"b": "pytest", "a": "render"} if not reverse else {"a": "render", "b": "pytest"}
    facts["filemap"] = {"a.py": "n", "z.py": "m"} if reverse else {"z.py": "m", "a.py": "n"}
    return facts


def test_stable_bytes_despite_key_order():
    a = render_prefix(_shuffled_facts(False))
    b = render_prefix(_shuffled_facts(True))
    assert a == b
    assert "\r" not in a
    assert a.endswith("\n")
    assert "PLACEHOLDER" not in a
    # Ordnung sys>tools>policy>filemap>task>query via Delimiter-Index
    idx = [a.index(f"=== CTX:{layer.upper()}:v1:START ===") for layer in LAYER_ORDER]
    assert idx == sorted(idx)


def test_golden_hash_deterministic():
    a = render_prefix(dict(reversed(list(GOLDEN_FACTS.items()))))
    b = render_prefix(dict(GOLDEN_FACTS))
    ha, hb = sha256_hex(a), sha256_hex(b)
    assert ha == hb
    assert len(ha) == 64 and re.fullmatch(r"[0-9a-f]{64}", ha)
    assert ha == GOLDEN_SHA, f"Golden-Hash drift: {ha} != {GOLDEN_SHA}"
    assert canonical_bytes(a) == a.encode("utf-8")
    assert b"\xef\xbb\xbf" not in canonical_bytes(a)


def test_switch_is_suffix_append_only():
    base = render_prefix(GOLDEN_FACTS)
    switched = render_prefix(GOLDEN_FACTS, switch="codex")
    assert "[SWITCH" not in base
    assert switched.startswith(base.rstrip("\n"))
    assert switched.endswith(" [SWITCH:v1:codex]\n")
    assert "\r" not in switched
