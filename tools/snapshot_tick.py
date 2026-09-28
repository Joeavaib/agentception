#!/usr/bin/env python3
"""Pre-Limit Snapshot Tick (s05-snapshot-hook, stdlib only).

Zweck (AGENTS.md R4/R5): kontinuierlicher Tick-Snapshot alle 5 Tool-Calls,
append-only jsonl (seq/ts/files/intent/next). Kein Rewrite, Denylist fuer
Secrets, 70/90 Budget-Warner, lokaler Heartbeat statt API-Ping.

Format pro Zeile (json, LF-only, UTF-8 ohne BOM):
  {"seq": int, "ts": "ISO-8601 UTC", "files": [...], "intent": "...", "next": "..."}

Regeln:
- Append-only: nur 'a'-Mode, nie Rewrite/Truncate (R4 Cutoff statt Kompression).
- Denylist: Werte mit Secret-Mustern werden zu "[redacted]" (kein Secret im Log).
- Budget-Warner: WARN bei 70% / 90% von SNAP_BUDGET_LINES (default 200).
- Heartbeat: nur lokale Datei (.rfg/heartbeat.json), nie Netzwerk/API-Ping.
- Tick-Kadenz: TICK_EVERY=5 (Aufrufer zaehlt, --tick schreibt genau eine Zeile).

Beispiele:
  python3 tools/snapshot_tick.py --tick --files tools/a.py --intent "s05 umsetzen" --next "verify"
  python3 tools/snapshot_tick.py --check
  python3 tools/snapshot_tick.py --heartbeat
  python3 tools/snapshot_tick.py --selftest
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

TICK_EVERY = 5
SNAP_DEFAULT = Path(".rfg/snap.log.jsonl")
HEARTBEAT_DEFAULT = Path(".rfg/heartbeat.json")
SNAP_BUDGET_LINES = 200
WARN70 = int(SNAP_BUDGET_LINES * 0.7)
WARN90 = int(SNAP_BUDGET_LINES * 0.9)
REDACTED = "[redacted]"

DENYLIST = (
    "api_key",
    "apikey",
    "secret",
    "passwd",
    "password",
    "token",
    "bearer",
    "private_key",
    "client_secret",
    "aws_secret",
    "openai",
    "anthropic",
    "github_pat",
)


def _norm_lf(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def sanitize(value: str) -> str:
    """Denylist-Filter: Treffer -> [redacted] (case-insensitive, Substring)."""
    low = value.lower()
    for pat in DENYLIST:
        if pat in low:
            return REDACTED
    return value


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_entries(snap: Path) -> list[dict]:
    if not snap.is_file():
        return []
    entries: list[dict] = []
    for line in snap.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entries.append(json.loads(line))
    return entries


def next_seq(snap: Path) -> int:
    return len(read_entries(snap)) + 1


def budget_status(count: int) -> str:
    if count >= WARN90:
        return f"warn90: {count}/{SNAP_BUDGET_LINES} (90% erreicht, Cutoff statt Kompression)"
    if count >= WARN70:
        return f"warn70: {count}/{SNAP_BUDGET_LINES} (70% erreicht)"
    return f"ok: {count}/{SNAP_BUDGET_LINES}"


def append_tick(snap: Path, files: list[str], intent: str, nxt: str) -> dict:
    """Genau eine Zeile appenden (nie Rewrite). Gibt Entry zurueck."""
    snap.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "seq": next_seq(snap),
        "ts": utc_now_iso(),
        "files": [sanitize(_norm_lf(f).strip()) for f in files],
        "intent": sanitize(_norm_lf(intent).strip())[:280],
        "next": sanitize(_norm_lf(nxt).strip())[:280],
    }
    line = json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    with snap.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")
    status = budget_status(entry["seq"])
    if status.startswith("warn"):
        print(f"snapshot-budget {status}", file=sys.stderr)
    return entry


def do_heartbeat(root: Path, hb: Path, seq: int = 0) -> Path:
    """Lokaler Heartbeat (Datei-Touch, kein Netzwerk/API-Ping)."""
    hb.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": utc_now_iso(), "seq": seq, "tick_every": TICK_EVERY, "local_only": True}
    hb.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return hb


def do_check(snap: Path) -> int:
    if not snap.is_file():
        print(f"check: FAIL ({snap} fehlt)")
        return 1
    entries = read_entries(snap)
    if not entries:
        print("check: FAIL (leer, mindestens 1 Eintrag erwartet)")
        return 1
    for i, e in enumerate(entries, start=1):
        if set(e.keys()) != {"seq", "ts", "files", "intent", "next"}:
            print(f"check: FAIL (Zeile {i}: Feldsatz falsch: {sorted(e.keys())})")
            return 1
        if e["seq"] != i:
            print(f"check: FAIL (Zeile {i}: seq={e['seq']} erwartet {i})")
            return 1
        blob = json.dumps(e, ensure_ascii=False).lower()
        for pat in DENYLIST:
            if pat != "openai" and pat != "anthropic" and pat in blob and REDACTED not in blob:
                print(f"check: FAIL (Zeile {i}: Denylist-Leak {pat!r})")
                return 1
        if "\r" in json.dumps(e):
            print(f"check: FAIL (Zeile {i}: CR gefunden)")
            return 1
    print(f"check: ok ({len(entries)} Eintraege, {budget_status(len(entries))})")
    return 0


def do_selftest(root: Path, snap: Path) -> int:
    snap.parent.mkdir(parents=True, exist_ok=True)
    before = snap.read_text(encoding="utf-8") if snap.is_file() else ""
    before_lines = before.splitlines()
    # 1. append-only: eine Zeile mit Secret-Muster -> muss redacted sein
    entry = append_tick(snap, ["tools/snapshot_tick.py"], "selftest api_key=XYZ must redact", "check")
    after_lines = snap.read_text(encoding="utf-8").splitlines()
    if len(after_lines) != len(before_lines) + 1:
        print(f"selftest: FAIL (append erwartet {len(before_lines) + 1}, got {len(after_lines)})")
        return 1
    if before_lines and after_lines[: len(before_lines)] != before_lines:
        print("selftest: FAIL (Rewrite erkannt, alte Zeilen veraendert)")
        return 1
    if "XYZ" in after_lines[-1] or "api_key=XYZ" in after_lines[-1].lower():
        print("selftest: FAIL (Denylist greift nicht)")
        return 1
    if REDACTED not in after_lines[-1]:
        print("selftest: FAIL (Redaction-Marker fehlt)")
        return 1
    # 2. Pflichtfelder + seq-Kontinuitaet
    if do_check(snap) != 0:
        print("selftest: FAIL (--check rot)")
        return 1
    # 3. Budget-Warner rechnet korrekt
    assert budget_status(0).startswith("ok")
    assert budget_status(WARN70).startswith("warn70")
    assert budget_status(WARN90).startswith("warn90")
    # 4. Heartbeat lokal (kein Netzwerk-Import im Modul: AST-Check)
    import ast as _ast
    from pathlib import Path as _P

    src = _P(__file__).read_text(encoding="utf-8")
    tree = _ast.parse(src)
    net_mods = {"socket", "requests", "urllib", "urllib.request", "http", "http.client"}
    found = set()
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in {m.split(".")[0] for m in net_mods}:
                    found.add(a.name)
        elif isinstance(node, _ast.ImportFrom):
            if (node.module or "").split(".")[0] in {m.split(".")[0] for m in net_mods}:
                found.add(node.module or "")
    if found:
        print(f"selftest: FAIL (Netzwerk-Import {sorted(found)}, nur lokaler Heartbeat erlaubt)")
        return 1
    # root-relativ aufloesen
    hb_path = root / str(HEARTBEAT_DEFAULT) if str(HEARTBEAT_DEFAULT).startswith(".") else HEARTBEAT_DEFAULT
    do_heartbeat(root, hb_path, seq=entry["seq"])
    if not hb_path.is_file():
        print("selftest: FAIL (heartbeat fehlt)")
        return 1
    # 5. LF-only / kein BOM
    raw = snap.read_bytes()
    if b"\r" in raw or raw.startswith(b"\xef\xbb\xbf"):
        print("selftest: FAIL (CR oder BOM im snap.log)")
        return 1
    print(f"selftest: ok (seq={entry['seq']}, tick_every={TICK_EVERY}, {budget_status(entry['seq'])})")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Pre-Limit Snapshot Tick (append-only jsonl)")
    ap.add_argument("--tick", action="store_true", help="genau eine Snapshot-Zeile appenden")
    ap.add_argument("--files", default="", help="kommagetrennte Dateiliste")
    ap.add_argument("--intent", default="", help="Kurzbeschreibung (<280ch)")
    ap.add_argument("--next", default="", help="naechster Schritt (<280ch)")
    ap.add_argument("--check", action="store_true", help="snap.log.jsonl validieren")
    ap.add_argument("--heartbeat", action="store_true", help="lokalen Heartbeat schreiben (kein Ping)")
    ap.add_argument("--selftest", action="store_true", help="Selftest (append+check+denylist+heartbeat)")
    ap.add_argument("--root", default=".", help="Repo-Root (default: .)")
    ap.add_argument("--snap", default=str(SNAP_DEFAULT), help="Pfad zu snap.log.jsonl")
    args = ap.parse_args(argv)
    root = Path(args.root)
    snap = Path(args.snap)
    if not snap.is_absolute():
        snap = root / snap
    if args.selftest:
        return do_selftest(root, snap)
    if args.check:
        return do_check(snap)
    if args.heartbeat:
        hb = root / str(HEARTBEAT_DEFAULT)
        entries = read_entries(snap)
        seq = entries[-1]["seq"] if entries else 0
        do_heartbeat(root, hb, seq=seq)
        print(f"heartbeat: ok ({hb}, seq={seq}, lokal, kein Ping)")
        return 0
    if args.tick:
        files = [f.strip() for f in args.files.split(",") if f.strip()]
        e = append_tick(snap, files, args.intent or "(tick)", args.next or "(next)")
        print(f"tick: ok seq={e['seq']} (alle {TICK_EVERY} Calls)")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
