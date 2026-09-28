=== CTX:CORE:v1:START ===
# AGENTS.md — Single Source of Truth (frozen core, static-first)
# ctx:schema=v1 | budget: core<=120 lines, switch<4k | LF-only UTF-8 no BOM

## 1. Identitaet
- KV-cache-nativer Tool-Switch: Claude Code -> Codex ohne Re-Explaining.
- AGENTS.md ist einzige pflegbare Quelle. CLAUDE.md ist duenner Shim.
- Cross-vendor kein KV-Sharing (Tokenizer). Ziel: Minimierung + intra-vendor Hits 80%+.
- Static-first: statisch vorne (cachebar), volatil hinten (Suffix-Append).

## 2. Regeln (frozen core)
- R1 Single-Source: keine Duplikate. CLAUDE.md importiert via @./AGENTS.md.
- R2 Static-first: niemals volatil in Prefix mischen. Volatiles nur letzte Zeile.
- R3 Stabile Delimiter: === CTX:<LAYER>:v1:START|END ===. Reihenfolge fix:
- sys > tools > policy > filemap > task > query. Switch als Suffix [SWITCH:v1].
- R4 Codex-Trunkierung sicher: Cutoff statt Kompression. Wichtiges vorne, kuerzbar hinten.
- R5 Verify-first: kein Handoff-Recycling ohne SHA==HEAD + Verify-gruen. TTL 2h.
- R6 LF-only, UTF-8, sortierte Keys/Listen. Deterministische Bytes (Golden-Hash).
- R7 Max 120 Zeilen AGENTS.md. CLAUDE.md max ~10 Zeilen. Keine Secrets im Kontext.

## 3. Architektur
- `AGENTS.md`: frozen core (dieses File). Prefix-kompatibel fuer Claude + Codex.
- `CLAUDE.md`: 5-Zeilen-Shim (Import + Claude-Extras). Kein Content-Duplikat.
- `tools/render_context.py`: deterministischer Prefix-Renderer (static-first, canonical).
- `context/handoff_schema.yaml` + `.handoff.md`: Resume-Paket max 1.2k Tokens.
- `tools/handoff_git.py`: Git-SHA als neutraler Anker (diff-stat, Blob-Pointer).
- `tools/snapshot_tick.py`: Pre-Limit Snapshot alle 5 Calls (append-only jsonl).
- `context/layer_budget.yaml`: L1 3k / L2 2k / L3 1.5k / L4 0.5k, Envelope 7k.
- `tools/verify_handoff.py`: Stale-Detektor (SHA-mismatch, mtime, TTL).
- `tools/switch_to_codex.sh`: One-Command Switch (S/M/L-Paket, copy-paste-resume).

## 4. Commands (sortiert)
- `bash -n tools/switch_to_codex.sh` — Syntaxcheck Switch-Script
- `python3 -m pytest tests/ -q` — Tests (Renderer Golden-Hash zuerst)
- `python3 tools/handoff_git.py --check` — Git-Anker pruefen
- `python3 tools/snapshot_tick.py --selftest` — Snapshot-Selftest
- `python3 tools/verify_handoff.py --selftest` — Handoff-Verifikation
- `tools/switch_to_codex.sh --help` — Switch-UX Hilfe
=== CTX:CORE:v1:END ===
<!-- ctx:schema=v1 volatile: date=<YYYY-MM-DD> branch=<name> -->
