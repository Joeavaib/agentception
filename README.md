# agentception — Tool-Switch ohne Re-Explaining

Wechsle zwischen KI-Coding-Tools (Claude Code, Codex, Opencode, Grok, …),
ohne Kontext neu zu erklären: stabiler Prefix vorne (Cache-Hit), Volatiles
hinten, Git-SHA als Anker statt Copy-Paste. Plain Markdown + stdlib-Skripte,
kein Vendor-Lock-in.

## Quickstart (nach dem Clonen)

```sh
cp .handoff.example.md .handoff.md   # 1. lokales Handoff anlegen (bleibt ungetrackt)
# 2. TODOs in .handoff.md fuellen: erstellt_am=jetzt (UTC), gueltig_bis=+2h, commit=HEAD-SHA
python3 tools/verify_handoff.py --check   # 3. Step-0: FRESH erwartet
python3 -m pytest tests/ -q               # 4. Tests gruen
tools/switch_to_codex.sh --check          # 5. Switch-Bereitschaft (Ampel S/M/L)
tools/switch_to_codex.sh --out paket.md   # 6. copy: Paket erzeugen, paste: im Ziel-Tool einfuegen, resume: dort Step-0 fahren
```

## Doku

- `AGENTS.md` — Single Source (frozen core, Regeln R1–R7)
- `docs/switch-ux.md` — Journey copy-paste-resume, Ampel, No-Bypass
- `docs/verify-first.md` — Step-0 Ritual, Stale-Detektor
- `docs/git-anchor.md` — WIP-Handoff via SHA/Blob-Pointer
- `docs/layer-budget.md` — Budget-Envelope 7k (L1–L4)
- `context/handoff_schema.yaml` — Resume-Paket-Kontrakt (max 1200 Tokens)

Regeln: kein Secret in Paket/Logs (Denylist), LF-only UTF-8 ohne BOM,
Cutoff statt Kompression, Volatiles nur als Suffix.
