#!/usr/bin/env python3
"""Git-Anker fuer WIP-Handoff (s04-git-anchor, stdlib only).

Zweck (AGENTS.md R5): Handoff via Git-SHA statt Copy-Paste.
Sender schickt SHA + Pointer, Empfaenger holt selbst via ``git show``.
Provenienz via SHA; ``.handoff.md`` Feld ``commit:`` wird gegen HEAD geprueft.

WIP-Flow (kein Commit noetig, funktioniert auch bei unborn HEAD):
  1. Sender: ``python3 tools/handoff_git.py --check`` (HEAD-SHA oder
     unborn-Hinweis, ``git status --short``, ``git diff --stat``).
  2. WIP-Pointer ohne Commit: ``git stash create -q`` liefert einen
     Commit-artigen SHA (dangling) als WIP-Anker. In ``.handoff.md``
     als ``commit: <SHA> (WIP, uncommitted)`` eintragen.
  3. Blob-Pointer: ``path@SHA:L-range`` zeigt auf Version im Objektstore,
     z. B. ``tools/render_context.py@abc1234:L49-58``.
  4. Empfaenger holt selbst (kein Copy-Paste)::

       git show <SHA>:<path>            # Datei in Version SHA zeigen
       git show <SHA> --stat            # WIP-Pointer (stash create) zeigen
       git show <blob-sha>              # Blob direkt zeigen
       git diff <SHA> HEAD --stat       # Drift seit Handoff pruefen

Siehe docs/git-anchor.md fuer Formate (WIP-Commit, Blob-Pointer, PR-Anker).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

MAX_STATUS_LINES = 20
HANDOFF_DEFAULT = Path(".handoff.md")


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
    # Branch-Namen bestimmen (unborn-Hinweis kontextualisieren)
    _, br = _run_git(["symbolic-ref", "--short", "HEAD"], root)
    branch = br.strip() if br.strip() else "unbekannt"
    return None, f"unborn (Branch '{branch}', noch keine Commits)"


def get_status(root: Path) -> list[str]:
    rc, out = _run_git(["status", "--short"], root)
    if rc != 0:
        return [f"(git status fehlgeschlagen: {out})"] if out else ["(kein Status)"]
    return out.splitlines() if out else []


def get_diffstat(root: Path) -> str:
    rc, out = _run_git(["diff", "--stat"], root)
    if rc != 0:
        return "(kein diff: unborn HEAD oder Fehler)"
    return out if out else "(clean: kein unstaged diff)"


def read_handoff_commit(path: Path) -> str | None:
    """commit:-Feld aus .handoff.md lesen, None wenn fehlt/unlesbar."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in text.replace("\r\n", "\n").split("\n"):
        m = re.match(r"\s*commit:\s*(.+?)\s*$", line)
        if m:
            return m.group(1)
    return None


def check_handoff_commit(handoff_field: str | None, head: str | None) -> str:
    if head is None:
        return "commit-check: ok (HEAD unborn, kein Vergleich moeglich)"
    if handoff_field is None:
        return "commit-check: WARN (.handoff.md ohne commit:-Feld)"
    # SHA aus Feld extrahieren (Format: "<sha> (...)" oder "n/a ...")
    m = re.search(r"[0-9a-f]{7,40}", handoff_field)
    if not m:
        return f"commit-check: WARN (kein SHA in commit:-Feld: {handoff_field!r})"
    short = m.group(0)
    if head.startswith(short) or short.startswith(head[:7]):
        return f"commit-check: ok (SHA==HEAD {head[:12]})"
    return f"commit-check: WARN (mismatch: handoff={short} vs HEAD={head[:12]})"


def do_check(root: Path, handoff: Path) -> int:
    head, hint = get_head(root)
    if head:
        print(f"HEAD: {head}")
    else:
        print(f"HEAD: {hint}")
    print(f"handoff: {handoff} ({'gefunden' if handoff.is_file() else 'fehlt'})")
    print("--- status --short (max 20) ---")
    lines = get_status(root)
    if not lines:
        print("(clean)")
    else:
        for ln in lines[:MAX_STATUS_LINES]:
            print(ln)
        if len(lines) > MAX_STATUS_LINES:
            print(f"... (+{len(lines) - MAX_STATUS_LINES} weitere)")
    print("--- diff --stat ---")
    print(get_diffstat(root))
    print("--- .handoff.md commit vs HEAD ---")
    field = read_handoff_commit(handoff) if handoff.is_file() else None
    print(check_handoff_commit(field, head))
    # Wichtig: --check immer exit 0 (auch unborn, auch mismatch -> nur WARN).
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Git-Anker --check: HEAD-SHA, status --short, diff --stat, "
        ".handoff.md commit-Abgleich.",
        epilog="WIP-Flow ohne Commit: `git stash create -q` als Pointer "
        "nutzen, Empfaenger holt via `git show <SHA>:<path>` oder "
        "`git show <SHA> --stat`. Details: docs/git-anchor.md.",
    )
    ap.add_argument("--check", action="store_true", help="Anker pruefen (exit 0, auch unborn)")
    ap.add_argument("--root", default=".", help="Repo-Root (default: .)")
    ap.add_argument("--handoff", default=str(HANDOFF_DEFAULT), help="Pfad zu .handoff.md")
    args = ap.parse_args(argv)
    if not args.check:
        ap.print_help()
        return 2
    return do_check(Path(args.root), Path(args.handoff))


if __name__ == "__main__":
    raise SystemExit(main())
