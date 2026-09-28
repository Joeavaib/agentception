# Layer-Budget L1-L4: Envelope 7k (s06)

Ziel: Switch-Paket 3-4k statt 20k. Envelope `max_tokens: 7000` (7k),
Summe L1 3k + L2 2k + L3 1.5k + L4 0.5k. Cutoff statt Kompression,
Default-Deny Filter, static-first (AGENTS.md R2/R4).

## 1. Layer (Budget siehe `context/layer_budget.yaml`)

- L1 3k gecacht: frozen core (`AGENTS.md`), stabiler Prefix, KV-Hit 80%+.
- L2 2k Pointer+Delta: Git-SHA, Blob-Pointer `path@SHA:L-range`, `diff --stat`.
- L3 1.5k Window: aktuelles Fenster (`.handoff.md` max 1.2k Tokens, Snapshot-Tick).
- L4 0.5k Profil: Tool-Profil + volatiles Suffix (`[SWITCH:v1]`, `erstellt_am`).

## 2. Default-Deny Filter

Nur Allow-Liste passiert: `AGENTS.md`, `context/handoff_schema.yaml`,
`context/layer_budget.yaml`. Drop: Secrets, Voll-Logs, unreferenzierte Diffs.
Negativ-Wissen als Signatur (<80ch), keine Payload-Bloat.

## 3. Cutoff-Regel (statt Kompression)

Bei Overflow hinten kuergen (L4 zuerst, dann L3), nie Prefix umschreiben:

```sh
# Budget-Check (chars ~= Tokens*4, Envelope 7000 max_tokens)
python3 -c "import pathlib; b=sum(len(p.read_bytes())//4 for p in [pathlib.Path('AGENTS.md')]); print(b)"
grep -q "max_tokens" context/layer_budget.yaml
```

## 4. Switch-Ampel (3-4k statt 20k)

- S <5k diff: skip, nur SHA (`git stash create -q` als WIP-Pointer).
- M 5-20k: 800-Tok-Paket (Handoff + Delta).
- L 20-80k: 1.5k-Paket (Handoff + Pointer + Window-Cutoff).

Empfaenger holt selbst via `git show <SHA>:<path>` (siehe `docs/git-anchor.md`).
Verify-first (R5): weiter nur bei SHA==HEAD + Tests gruen.
