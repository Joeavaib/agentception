# agentception — Tool-Switch without Re-Explaining

Switch between AI coding tools (Claude Code, Codex, Opencode, Grok, …)
without re-explaining context: stable prefix first (cache hit), volatiles
last, Git-SHA as anchor instead of copy-paste. Plain Markdown + stdlib
scripts, no vendor lock-in.

> Deutsche Version: [README.de.md](README.de.md)

## Quickstart (after cloning)

```sh
cp .handoff.example.md .handoff.md   # 1. create local handoff (stays untracked)
# 2. fill TODOs in .handoff.md: erstellt_am=now (UTC), gueltig_bis=+2h, commit=HEAD-SHA
python3 tools/verify_handoff.py --check   # 3. Step-0: expect FRESH
python3 -m pytest tests/ -q               # 4. tests green
tools/switch_to_codex.sh --check          # 5. switch readiness (level S/M/L)
tools/switch_to_codex.sh --out packet.md  # 6. copy: build packet, paste: insert in target tool, resume: run Step-0 there
```

## Docs

- `AGENTS.md` — Single Source (frozen core, rules R1–R7)
- `docs/switch-ux.md` — copy-paste-resume journey, level, No-Bypass
- `docs/verify-first.md` — Step-0 ritual, stale detector
- `docs/git-anchor.md` — WIP handoff via SHA/blob pointer
- `docs/layer-budget.md` — budget envelope 7k (L1–L4)
- `context/handoff_schema.yaml` — resume-packet contract (max 1200 tokens)

Rules: no secrets in packets/logs (denylist), LF-only UTF-8 without BOM,
cutoff instead of compression, volatiles as suffix only.
