#!/usr/bin/env python3
"""Verify-First Anti-Stale (s07-verify-first, stdlib only).

Zweck (AGENTS.md R5): kein Handoff-Recycling ohne SHA==HEAD + Verify-gruen.
Handoff-Kontrakt mit TTL+Provenienz (erstellt_am/commit/gueltig_bis+2h),
Step-0 Ritual (SHA==HEAD, Read, Verify-gruen), Stale-Detektor
(SHA-mismatch/mtime/TTL), kein Zombie-Recycling.

Step-0 Ritual (Empfaenger, vor jedem Resume):
  1. SHA: ``python3 tools/handoff_git.py --check`` -> SHA==HEAD
     (oder WIP-SHA bekannt, oder HEAD unborn -> Hinweis ok).
  2. Read: ``.handoff.md`` lesen, Pflichtfelder + Pointer pruefen.
  3. Verify-gruen: ``python3 tools/verify_handoff.py --check``
     (TTL frisch, mtime ok) + Tests gruen (``python3 -m pytest tests/ -q``).

Stale-Faelle (-> STOP, kein Recycling, neues Handoff anfordern):
  - SHA-mismatch: commit:-SHA != HEAD (Drift seit Handoff).
  - TTL-expired: jetzt > gueltig_bis (TTL 2h ab erstellt_am).
  - TTL-Bruch: gueltig_bis != erstellt_am + 2h (Kontrakt verletzt).
  - mtime-stale: Datei nach gueltig_bis geaendert (Zombie-Recycling).
  - Feld fehlt: Pflichtfeld aus context/handoff_schema.yaml fehlt.

Beispiele:
  python3 tools/verify_handoff.py --check
  python3 tools/verify_handoff.py --selftest
  python3 tools/verify_handoff.py --check --root . --handoff .handoff.md
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

TTL_SECONDS = 7200  # 2h (AGENTS.md R5, handoff_schema: gueltig_bis = erstellt_am + 2h)
TTL_TOLERANCE = 60  # Sekunden Toleranz fuer Rundung
HANDOFF_DEFAULT = Path(".handoff.md")

REQUIRED_FIELDS = (
    "goal",
    "constraints",
    "done",
    "tried_failed",
    "next_steps",
    "verify",
    "pointers",
    "erstellt_am",
    "commit",
    "gueltig_bis",
)

DENYLIST = (
    "api_key",
    "apikey",
    "secret",
    "passwd",
    "password",
    "private_key",
    "github_pat",
    "bearer",
)


def _run_git(args: list[str], cwd: Path) -> tuple[int, str]:
    """git aufrufen, (returncode, stdout+stderr als Text) liefern."""
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=15,
        )
        return p.returncode, p.stdout.strip("\n")
    except FileNotFoundError:
        return 127, "git nicht gefunden (PATH?)"
    except subprocess.TimeoutExpired:
        return 124, "git timeout"


def get_head(root: Path) -> tuple[str | None, str]:
    """HEAD-SHA oder (None, unborn-Hinweis). Exit 0-faehig ohne Commits."""
    rc, out = _run_git(["rev-parse", "HEAD"], root)
    if rc == 0 and re.fullmatch(r"[0-9a-f]{40}", out.strip()):
        return out.strip(), ""
    _, br = _run_git(["symbolic-ref", "--short", "HEAD"], root)
    branch = br.strip() if br.strip() else "unbekannt"
    return None, f"unborn (Branch '{branch}', noch keine Commits)"


def parse_iso_z(s: str) -> datetime | None:
    """ISO-8601 mit Z/Offset parsen, naive -> UTC. None bei Fehler."""
    t = s.strip().strip("'\"")
    if not t:
        return None
    try:
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def read_field(text: str, name: str) -> str | None:
    """Erste Zeile `name: <wert>` finden (Frontmatter-kompatibel).

    Leere Werte (`constraints:` + Folgeliste) liefern "" zurueck;
    None nur wenn die `name:`-Zeile ganz fehlt.
    """
    norm = text.replace("\r\n", "\n")
    for line in norm.split("\n"):
        m = re.match(r"\s*" + re.escape(name) + r":\s*(.*?)\s*$", line)
        if m:
            val = m.group(1)
            return val if val else ""
    return None


def has_field(text: str, name: str) -> bool:
    """`name:`-Zeile vorhanden (Wert darf leer/Liste sein)?"""
    return read_field(text, name) is not None


def missing_fields(text: str) -> list[str]:
    """Pflichtfelder aus handoff_schema, die als `feld:`-Zeile fehlen."""
    return [f for f in REQUIRED_FIELDS if not has_field(text, f)]


def check_provenance(text: str, now: datetime) -> tuple[str, bool]:
    """TTL+Provenienz: erstellt_am/gueltig_bis parsebar, +2h, nicht expired."""
    erstellt_raw = read_field(text, "erstellt_am")
    gueltig_raw = read_field(text, "gueltig_bis")
    if erstellt_raw is None or gueltig_raw is None:
        return ("provenance: FAIL (erstellt_am/gueltig_bis fehlt)", False)
    erstellt = parse_iso_z(erstellt_raw)
    gueltig = parse_iso_z(gueltig_raw)
    if erstellt is None:
        return (f"provenance: FAIL (erstellt_am unparsebar: {erstellt_raw!r})", False)
    if gueltig is None:
        return (f"provenance: FAIL (gueltig_bis unparsebar: {gueltig_raw!r})", False)
    delta = (gueltig - erstellt).total_seconds()
    if abs(delta - TTL_SECONDS) > TTL_TOLERANCE:
        return (
            f"provenance: STALE (TTL-Bruch: gueltig-erstellt={int(delta)}s, erwartet {TTL_SECONDS}s)",
            False,
        )
    if now > gueltig:
        late = int((now - gueltig).total_seconds())
        return (f"provenance: STALE (TTL-expired seit {late}s, gueltig_bis={gueltig_raw})", False)
    left = int((gueltig - now).total_seconds())
    return (f"provenance: ok (TTL frisch, Rest {left}s bis {gueltig_raw})", True)


def object_exists(root: Path, sha: str) -> bool:
    """SHA im Objektstore? (`git cat-file -e`, erkennt WIP-Pointer aus `stash create`)."""
    rc, _ = _run_git(["cat-file", "-e", sha], root)
    return rc == 0


def check_sha(commit_field: str | None, head: str | None, root: Path | None = None) -> tuple[str, bool]:
    """SHA==HEAD (unborn -> ok mit Hinweis, mismatch -> STALE).

    WIP-Ausnahme (docs/git-anchor.md): Feld mit WIP-Marker + SHA, das als
    Objekt im Repo existiert (`git stash create -q`), ist ok ohne HEAD-Match.
    WIP-Marker ohne Objekt -> STALE (kein Zombie-Recycling, kein Cross-Machine-
    Paste von Uncommittedem).
    """
    if head is None:
        return ("sha: ok (HEAD unborn, kein Vergleich moeglich)", True)
    if not commit_field:
        return ("sha: FAIL (commit:-Feld fehlt/leer)", False)
    m = re.search(r"[0-9a-f]{7,40}", commit_field)
    if not m:
        return (f"sha: WARN (kein SHA in commit:-Feld: {commit_field!r}, n/a unborn?)", True)
    short = m.group(0)
    if head.startswith(short) or short.startswith(head[:7]):
        return (f"sha: ok (SHA==HEAD {head[:12]})", True)
    if "wip" in commit_field.lower():
        if root is not None and object_exists(root, short):
            return (f"sha: ok (WIP-SHA bekannt, Objekt {short[:12]} vorhanden)", True)
        return (f"sha: STALE (WIP-SHA {short[:12]} ohne Objekt: Uncommittedes nicht per Paste uebertragbar)", False)
    return (f"sha: STALE (SHA-mismatch: handoff={short} vs HEAD={head[:12]})", False)


def check_mtime(path: Path, gueltig: datetime | None) -> tuple[str, bool]:
    """mtime nach gueltig_bis -> Zombie-Recycling (STALE)."""
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError as e:
        return (f"mtime: FAIL ({e})", False)
    if gueltig is not None and mtime > gueltig + timedelta(seconds=TTL_TOLERANCE):
        return (
            f"mtime: STALE (geaendert {mtime.isoformat()} nach gueltig_bis "
            f"{gueltig.isoformat()}, Zombie-Verdacht)",
            False,
        )
    return (f"mtime: ok ({mtime.isoformat()})", True)


def check_bytes(path: Path) -> tuple[str, bool]:
    """LF-only, kein BOM, kein Secret-Muster (Zuweisung, keine Erwaehnung)."""
    try:
        raw = path.read_bytes()
    except OSError as e:
        return (f"bytes: FAIL ({e})", False)
    if raw.startswith(b"\xef\xbb\xbf"):
        return ("bytes: FAIL (BOM gefunden, LF-only UTF-8 ohne BOM erwartet)", False)
    if b"\r" in raw:
        return ("bytes: FAIL (CR gefunden, LF-only erwartet)", False)
    # Secret nur bei Zuweisung `key[:=] wert` werten; reine Erwaehnung
    # ("kein Secret", "ohne Password") ist Dokumentation, kein Leak.
    text = raw.decode("utf-8", errors="replace")
    pat = "(" + "|".join(re.escape(d) for d in DENYLIST) + ")"
    for line in text.split("\n"):
        low = line.lower()
        if "kein" in low or "keine" in low or "ohne" in low or "no " in low:
            continue
        m = re.search(pat + r"\s*[:=]\s*['\"]?(\S+)", low)
        if m and m.group(2) not in ("", "-", "n/a"):
            return (f"bytes: FAIL (Denylist-Zuweisung {m.group(1)!r}, kein Secret im Handoff)", False)
    return ("bytes: ok (LF-only, kein BOM, kein Secret)", True)


def do_check(root: Path, handoff: Path, now: datetime | None = None) -> int:
    """Step-0 Diagnose: SHA + Read + TTL + mtime. 0=frisch, 1=stale/fail."""
    now = now or datetime.now(timezone.utc)
    print(f"handoff: {handoff} ({'gefunden' if handoff.is_file() else 'fehlt'})")
    if not handoff.is_file():
        print("result: FAIL (Datei fehlt, kein Resume moeglich)")
        return 1
    try:
        text = handoff.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"result: FAIL (unlesbar: {e})")
        return 1
    head, hint = get_head(root)
    if head:
        print(f"HEAD: {head}")
    else:
        print(f"HEAD: {hint}")
    ok_all = True
    # 1. SHA
    msg, ok = check_sha(read_field(text, "commit"), head, root)
    print(msg)
    ok_all &= ok
    # 2. Read (Pflichtfelder)
    miss = missing_fields(text)
    if miss:
        print(f"read: FAIL (Pflichtfelder fehlen: {', '.join(miss)})")
        ok_all = False
    else:
        print(f"read: ok ({len(REQUIRED_FIELDS)} Pflichtfelder vorhanden)")
    # 3. Provenienz/TTL
    msg, ok = check_provenance(text, now)
    print(msg)
    ok_all &= ok
    # 4. mtime vs gueltig_bis
    gueltig_raw = read_field(text, "gueltig_bis")
    gueltig = parse_iso_z(gueltig_raw) if gueltig_raw else None
    msg, ok = check_mtime(handoff, gueltig)
    print(msg)
    ok_all &= ok
    # 5. Bytes/Secrets
    msg, ok = check_bytes(handoff)
    print(msg)
    ok_all &= ok
    if ok_all:
        print("result: FRESH (SHA==HEAD + Read + TTL frisch -> Resume erlaubt)")
        return 0
    print("result: STALE (STOP, kein Zombie-Recycling, neues Handoff anfordern)")
    return 1


def _fixture(base: datetime, commit: str, hours_ago_created: float = 0.5) -> str:
    """Gueltige Handoff-Fixture bauen (TTL exakt +2h)."""
    erstellt = (base - timedelta(hours=hours_ago_created)).isoformat().replace("+00:00", "Z")
    gueltig = (base - timedelta(hours=hours_ago_created) + timedelta(seconds=TTL_SECONDS)).isoformat().replace(
        "+00:00", "Z"
    )
    lines = [
        "---",
        "goal: selftest-fixture",
        "constraints:",
        "  - static-first",
        "done:",
        "  - s07 fixture ok",
        "tried_failed:",
        "  - a->b->c",
        "next_steps:",
        "  - [ ] weiter",
        "verify: python3 tools/verify_handoff.py --selftest",
        "pointers:",
        "  - tools/verify_handoff.py:1",
        f"erstellt_am: {erstellt}",
        f"commit: {commit}",
        f"gueltig_bis: {gueltig}",
        "---",
        "# fixture",
    ]
    return "\n".join(lines) + "\n"


def do_selftest(root: Path) -> int:
    """Selftest ohne Repo-Seiteneffekte (Tempdir-Fixtures + AST-Netzcheck)."""
    now = datetime.now(timezone.utc)
    head, _ = get_head(root)
    # Anker-SHA: echter HEAD wenn vorhanden, sonst synthetischer (unborn-Pfad
    # wird separat mit nicht-git-root geprueft).
    anchor = head if head else "a" * 40
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # 1. FRESH: gueltig + passender SHA -> exit 0
        fresh = tmp / "fresh.md"
        fresh.write_text(_fixture(now, anchor), encoding="utf-8", newline="\n")
        if do_check(root, fresh, now) != 0:
            print("selftest: FAIL (fresh-Fixture sollte FRESH sein)")
            return 1
        # 2. SHA-mismatch -> STALE (Funktionsebene, repo-unabhaengig)
        msg, ok = check_sha("a" * 40, "b" * 40)
        if ok or "STALE" not in msg:
            print(f"selftest: FAIL (SHA-mismatch Funktionstest: {msg})")
            return 1
        msg, ok = check_sha("a" * 40, "a" * 40)
        if not ok or "ok" not in msg:
            print(f"selftest: FAIL (SHA-match Funktionstest: {msg})")
            return 1
        # 2b. WIP-Ausnahme: Marker + vorhandenes Objekt -> ok, ohne Objekt -> STALE
        import subprocess as _sp

        wip_root = tmp / "wiprepo"
        wip_root.mkdir()
        _sp.run(["git", "init", "-q", "-b", "master"], cwd=str(wip_root), check=True)
        (wip_root / "f.txt").write_text("x\n", encoding="utf-8")
        _sp.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"], cwd=str(wip_root), check=True)
        _sp.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "wip"],
            cwd=str(wip_root),
            check=True,
        )
        (wip_root / "f.txt").write_text("y\n", encoding="utf-8")
        wip_sha = _sp.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", "stash", "create", "-q"],
            cwd=str(wip_root),
            capture_output=True,
            text=True,
        ).stdout.strip()
        if not wip_sha:
            print("selftest: FAIL (kein WIP-SHA erzeugbar)")
            return 1
        wip_head, _ = get_head(wip_root)
        msg, ok = check_sha(f"{wip_sha} (WIP, uncommitted)", wip_head, wip_root)
        if not ok or "WIP" not in msg:
            print(f"selftest: FAIL (WIP mit Objekt sollte ok sein: {msg})")
            return 1
        msg, ok = check_sha(f"{'d' * 40} (WIP, uncommitted)", wip_head, wip_root)
        if ok or "STALE" not in msg:
            print(f"selftest: FAIL (WIP ohne Objekt sollte STALE sein: {msg})")
            return 1
        if head:
            bad = tmp / "mismatch.md"
            other = ("b" if head[0] != "b" else "c") + head[1:]
            bad.write_text(_fixture(now, other), encoding="utf-8", newline="\n")
            if do_check(root, bad, now) == 0:
                print("selftest: FAIL (SHA-mismatch nicht erkannt)")
                return 1
        else:
            print("selftest: Hinweis (HEAD unborn, Repo-Mismatch entf., Funktionstest ok)")
        # 3. TTL-expired -> STALE
        old = tmp / "expired.md"
        old_base = now - timedelta(hours=5)
        old.write_text(_fixture(old_base, anchor), encoding="utf-8", newline="\n")
        if do_check(root, old, now) == 0:
            print("selftest: FAIL (TTL-expired nicht erkannt)")
            return 1
        # 4. TTL-Bruch (gueltig != erstellt+2h) -> STALE
        brk = tmp / "broken-ttl.md"
        t = _fixture(now, anchor).replace("+00:00", "Z")
        lines = [ln for ln in t.splitlines() if not ln.startswith("gueltig_bis:")]
        erstellt_raw = read_field(t, "erstellt_am") or ""
        erstellt = parse_iso_z(erstellt_raw) or now
        wrong = (erstellt + timedelta(hours=5)).isoformat().replace("+00:00", "Z")
        lines.insert(-1, f"gueltig_bis: {wrong}")
        brk.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        if do_check(root, brk, now) == 0:
            print("selftest: FAIL (TTL-Bruch nicht erkannt)")
            return 1
        # 5. Pflichtfeld fehlt -> FAIL
        miss = tmp / "missing.md"
        mtext = _fixture(now, anchor).splitlines()
        mtext = [ln for ln in mtext if not ln.startswith("goal:")]
        miss.write_text("\n".join(mtext) + "\n", encoding="utf-8", newline="\n")
        if do_check(root, miss, now) == 0:
            print("selftest: FAIL (fehlendes Pflichtfeld nicht erkannt)")
            return 1
        # 6. mtime nach gueltig_bis -> STALE (Zombie)
        zom = tmp / "zombie.md"
        zom.write_text(_fixture(now, anchor), encoding="utf-8", newline="\n")
        future_gueltig = now - timedelta(hours=1)
        erstellt_z = (future_gueltig - timedelta(seconds=TTL_SECONDS)).isoformat().replace("+00:00", "Z")
        ztext = zom.read_text(encoding="utf-8")
        ztext = re.sub(r"erstellt_am:.*", f"erstellt_am: {erstellt_z}", ztext)
        ztext = re.sub(r"gueltig_bis:.*", f"gueltig_bis: {future_gueltig.isoformat().replace('+00:00', 'Z')}", ztext)
        zom.write_text(ztext, encoding="utf-8", newline="\n")
        if do_check(root, zom, now) == 0:
            print("selftest: FAIL (mtime-Zombie nicht erkannt)")
            return 1
        # 7. CR/BOM/Secret abgewiesen
        cr = tmp / "cr.md"
        cr.write_bytes(_fixture(now, anchor).replace("\n", "\r\n").encode("utf-8"))
        msg, ok = check_bytes(cr)
        if ok:
            print(f"selftest: FAIL (CR nicht erkannt: {msg})")
            return 1
        sec = tmp / "sec.md"
        sec.write_text(_fixture(now, anchor) + "note: api_key=XYZ\n", encoding="utf-8", newline="\n")
        msg, ok = check_bytes(sec)
        if ok:
            print(f"selftest: FAIL (Secret nicht erkannt: {msg})")
            return 1
    # 8. Kein Netzwerk-Import (nur lokaler Check, kein API-Ping)
    import ast as _ast

    src = Path(__file__).read_text(encoding="utf-8")
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
        print(f"selftest: FAIL (Netzwerk-Import {sorted(found)}, nur lokale Pruefung erlaubt)")
        return 1
    # 9. LF-only / kein BOM im eigenen Modul
    raw = Path(__file__).read_bytes()
    if b"\r" in raw or raw.startswith(b"\xef\xbb\xbf"):
        print("selftest: FAIL (CR oder BOM im Modul)")
        return 1
    print(f"selftest: ok (TTL={TTL_SECONDS}s, Felder={len(REQUIRED_FIELDS)}, HEAD={'unborn' if not head else head[:12]})")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Verify-First Anti-Stale: SHA==HEAD + TTL + mtime pruefen.")
    ap.add_argument("--check", action="store_true", help="echtes .handoff.md pruefen (0=frisch, 1=stale)")
    ap.add_argument("--selftest", action="store_true", help="Selftest mit Temp-Fixtures (exit 0 erwartet)")
    ap.add_argument("--root", default=".", help="Repo-Root (default: .)")
    ap.add_argument("--handoff", default=str(HANDOFF_DEFAULT), help="Pfad zu .handoff.md")
    args = ap.parse_args(argv)
    root = Path(args.root)
    handoff = Path(args.handoff)
    if not handoff.is_absolute():
        handoff = root / handoff
    if args.selftest:
        return do_selftest(root)
    if args.check:
        return do_check(root, handoff)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
