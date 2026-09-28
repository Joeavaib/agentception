# Verify-First Anti-Stale: Step-0 Ritual (s07)

Ziel: kein Zombie-Recycling. Weiter nur bei SHA==HEAD + Read + Verify-gruen
(AGENTS.md R5). Handoff-Traeger: `.handoff.md` mit TTL+Provenienz
(`erstellt_am`/`commit`/`gueltig_bis`, TTL 2h, siehe `context/handoff_schema.yaml`).

## 1. Step-0 Ritual (Empfaenger, vor jedem Resume)

```sh
python3 tools/handoff_git.py --check      # 1. SHA: SHA==HEAD (oder WIP-SHA/unborn ok)
python3 tools/verify_handoff.py --check   # 2+3. Read+TTL+mtime: FRESH erwartet
python3 -m pytest tests/ -q               # 4. Tests gruen (Renderer Golden-Hash zuerst)
```

Nur bei `result: FRESH` + Tests gruen resume. Sonst STOP, neues Handoff anfordern.

## 2. Stale-Detektor (`tools/verify_handoff.py`)

| Fall | Signal | Folge |
| --- | --- | --- |
| SHA-mismatch | `commit:`-SHA != HEAD | STALE (Drift seit Handoff, `git diff <SHA> HEAD --stat`) |
| TTL-expired | jetzt > `gueltig_bis` | STALE (TTL 2h um, kein Recycling) |
| TTL-Bruch | `gueltig_bis` != `erstellt_am` + 2h | STALE (Kontrakt verletzt) |
| mtime-stale | Datei nach `gueltig_bis` geaendert | STALE (Zombie-Verdacht) |
| Feld fehlt | Pflichtfeld fehlt | FAIL (Schema: goal/constraints/done/tried_failed/next_steps/verify/pointers/erstellt_am/commit/gueltig_bis) |
| Secret/CR/BOM | Denylist/CR/BOM | FAIL (kein Secret, LF-only UTF-8 ohne BOM) |

Unborn HEAD (keine Commits): SHA-Check ok mit Hinweis, TTL+Read+mtime entscheiden.

## 3. Selftest + Regeln

```sh
python3 tools/verify_handoff.py --selftest   # Temp-Fixtures: fresh/mismatch/expired/TTL-Bruch/Feld-missing/Zombie/CR/Secret
```

Regeln: stdlib only, kein Netzwerk (nur lokale Pruefung), deterministisch,
Cutoff statt Kompression (R4). Sender-Seite: `commit:` + `erstellt_am`/`gueltig_bis`
(+2h) setzen, Empfaenger holt Inhalt via `git show <SHA>:<path>` (siehe `docs/git-anchor.md`).
