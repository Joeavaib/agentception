# Git-Anker: WIP-Handoff via SHA (s04)

Ziel: kein Copy-Paste. Sender schickt SHA + Pointer, Empfaenger holt via `git show`.

## 1. WIP-Handoff-Commit Format

In `.handoff.md`, Feld `commit:` (eine Zeile):

- Mit Commit: `commit: <40ch-SHA> (Branch, clean/dirty)`
- WIP ohne Commit: `commit: <SHA-von-stash-create> (WIP, uncommitted)`
- Unborn (kein Commit existiert): `commit: n/a (master unborn, clean)`

WIP-Pointer erzeugen: `git stash create -q` (kein Commit, nur dangling SHA).

## 2. Blob-Pointer Syntax

Format: `path@SHA:L-range` (Datei, Version, Zeilen):

- `tools/render_context.py@abc1234:L49-58`
- `AGENTS.md@HEAD:L1-10` (HEAD als SHA-Alias erlaubt)
- `context/handoff_schema.yaml@5bb192f:L1-20`

Regel: Pfad repo-relativ, SHA kurz (7+) oder voll, Range `L<von>-<bis>` oder `L<nr>`.

## 3. PR-Anker

Format: `repo#PR@SHA` (Provenienz: welcher PR-Stand gemeint ist):

- `inception#12@abc1234` (PR 12, Head-SHA abc1234)
- Empfaenger: PR fetch/checkout, dann `git diff <SHA> HEAD --stat` (Drift-Check).

## 4. Empfaenger-Rezept

```sh
python3 tools/handoff_git.py --check   # eigener Stand vs Handoff-SHA
git show <SHA>:<path>                  # Datei in Handoff-Version
git show <SHA> --stat                  # WIP-Pointer (stash create) ansehen
git show <blob-sha>                    # Blob direkt
git diff <SHA> HEAD --stat             # Drift seit Handoff
```

Verify-first (R5): weiter nur bei SHA==HEAD (oder WIP-SHA bekannt) + Tests gruen.
