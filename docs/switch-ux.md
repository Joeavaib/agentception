# Switch-UX: One-Command Claude -> Codex (s08)

Ziel: Ein Command, kein Re-Explaining. `tools/switch_to_codex.sh` generiert ein
deterministisches Paste-Paket (static-first, Cutoff statt Kompression).
Empfaenger ist Codex (oder ein frischer Claude-Kontext).

## 1. Journey in 3 Steps (copy-paste-resume)

```sh
tools/switch_to_codex.sh --check            # Gates pruefen (Ampel + Handoff frisch?)
tools/switch_to_codex.sh [--auto] --out paket.md   # 1. copy: Paket erzeugen
# 2. paste: paket.md in Codex einfuegen (kein Re-Explaining noetig)
# 3. resume: Codex faehrt Step-0 (SHA==HEAD + Verify-gruen, docs/verify-first.md)
```

Empfaenger holt Gekuerztes selbst: `git show <SHA>:<path>` (docs/git-anchor.md).

## 2. Ampel (Delta -> Paketklasse, Budget siehe context/layer_budget.yaml)

| Klasse | Delta | Paket | Inhalt |
| --- | --- | --- | --- |
| S | <5k | skip, nur SHA-Zeile | kein Paket noetig, Resume via SHA + `.handoff.md` |
| M | 5-20k | 800 Tokens (~3200 chars) | AGENTS.md + Handoff + Delta, Cutoff hinten |
| L | 20-80k | 1.5k Tokens (~6000 chars) | + Pointer + Window, Cutoff hinten |
| XL | >80k | L-Paket + WARN | Cutoff, nie Prefix umschreiben |

`--auto` (Default) klassifiziert via `git diff` + untracked Dateien (ohne
Scratch: `.rfg/`, `__pycache__/`, `.pytest_cache/`, `.benchmarks/`).
`--size S|M|L` waehlt die Klasse vor (Reduktion), aendert nie die Gates.

Paket-Ordnung (static-first): `CTX:CORE` (AGENTS.md, cachebar) ->
`CTX:HANDOFF` (`.handoff.md`) -> `CTX:POINTER` (SHA, Ampel, diff-stat) ->
Suffix `[SWITCH:v1:codex]`. Ueberschuss faellt hinten weg (CUTOFF-Marker),
der Prefix bleibt byte-identisch (KV-Cache-Hit).

## 3. No-Bypass Compliance (nur Reduktion+Cache)

- Gates vor jedem Paket: `.handoff.md` vorhanden + frisch
  (`tools/verify_handoff.py --check`). STALE -> Abbruch (Exit 1).
- Es gibt bewusst kein `--force`/`--skip-verify`: Bypass ist unmoeglich.
- Reduktion nur via Cutoff hinten + Cache-Pointer (SHA statt Volltext).
  Empfaenger verifiziert (Step-0) statt zu vertrauen.
- Determinismus: gleiche Tree-Lage -> gleiche Bytes (keine Timestamps im
  Paket; Volatiles stehen in `.handoff.md`: `erstellt_am`/`gueltig_bis`).
