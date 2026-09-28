#!/usr/bin/env bash
# switch_to_codex.sh — One-Command Switch Claude -> Codex (s08, bash only).
#
# Zweck (AGENTS.md R2/R4/R5): Ein Command generiert ein deterministisches
# Paste-Paket fuer den Tool-switch. Static-first (stabil vorne, volatil hinten),
# Cutoff statt Kompression, No-Bypass (kein --force, Gates sind Pflicht).
#
# 3-Step Journey (copy-paste-resume):
#   1. copy:   tools/switch_to_codex.sh [--auto] > paket.md (oder --out FILE)
#   2. paste:  Paket in Codex einfuegen (Paste, kein Re-Explaining).
#   3. resume: Codex faehrt Step-0 Ritual (SHA==HEAD + Verify-gruen, siehe
#              docs/verify-first.md) und holt Rest via git show <SHA>:<path>.
#
# Ampel (Delta-Groesse -> Paketklasse):
#   S <5k:      skip, nur SHA-Zeile (kein Paket noetig).
#   M 5-20k:    800-Tok-Paket (~3200 chars, Handoff + Delta, Cutoff hinten).
#   L 20-80k:   1.5k-Paket (~6000 chars, Handoff + Pointer + Window, Cutoff).
#   XL >80k:    L-Paket + WARN (Cutoff, nie Prefix umschreiben).
#
# No-Bypass Compliance (nur Reduktion+Cache):
#   - Vor jedem Paket laufen die Gates: .handoff.md vorhanden + frisch
#     (tools/verify_handoff.py --check). STALE -> Abbruch (Exit 1).
#   - Es gibt bewusst KEIN --force/--skip-verify (Bypass unmoeglich).
#   - Reduktion nur via Cutoff hinten; Empfaenger holt Gekuertes via Git-SHA.
#   - --size waehlt nur die Paketklasse (Reduktion), nie die Gates ab.
#
# Determinismus: LC_ALL=C, sortierte Listen, keine Timestamps im Paket
# (Volatiles stehen in .handoff.md: erstellt_am/gueltig_bis). Gleiche
# Tree-Lage -> gleiche Bytes. Volatiles nur als Suffix [SWITCH:v1:codex].
set -euo pipefail
export LC_ALL=C

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HANDOFF="$ROOT/.handoff.md"
AGENTS="$ROOT/AGENTS.md"

S_MAX=5000
M_MAX=20000
L_MAX=80000
M_PAKET_CHARS=3200
L_PAKET_CHARS=6000
SWITCH_SUFFIX=" [SWITCH:v1:codex]"

# Scratch-Dirs zaehlen nie zum Delta (kein Switch-Payload).
EXCLUDE_RE='^(\.git/|\.rfg/|.*__pycache__/.*|\.pytest_cache/.*|\.benchmarks/.*)$'

usage() {
  cat <<'EOF'
switch_to_codex.sh — One-Command switch Claude -> Codex (Paste-Paket, deterministisch)

Usage:
  tools/switch_to_codex.sh [--auto] [--size S|M|L] [--out FILE]
  tools/switch_to_codex.sh --json [--size S|M|L] [--out FILE]
  tools/switch_to_codex.sh --check
  tools/switch_to_codex.sh --help

Journey (copy-paste-resume):
  1. copy:   Paket erzeugen (stdout oder --out FILE)
  2. paste:  Paket in Codex einfuegen
  3. resume: Codex prueft Step-0 (SHA==HEAD + Verify-gruen) und macht weiter

Ampel: S <5k skip (nur SHA), M 5-20k 800-Tok-Paket, L 20-80k 1.5k-Paket, XL Cutoff+WARN.
No-Bypass: Gates (Handoff frisch) sind Pflicht, kein --force. Details: docs/switch-ux.md.
EOF
}

fail() { echo "switch: FAIL ($*)" >&2; exit 1; }

head_sha() {
  if sha=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null); then
    printf '%s\n' "$sha"
  else
    branch=$(git -C "$ROOT" symbolic-ref --short HEAD 2>/dev/null || echo unbekannt)
    printf 'n/a (%s unborn, keine Commits)\n' "$branch"
  fi
}

payload_bytes() {
  # Delta-Groesse in Bytes: unstaged diff + untracked Quelldateien (ohne Scratch).
  local diff_bytes=0 un_bytes=0
  diff_bytes=$(git -C "$ROOT" diff 2>/dev/null | wc -c)
  un_bytes=$(
    git -C "$ROOT" status --porcelain 2>/dev/null \
      | grep '^?? ' | cut -c4- \
      | while IFS= read -r f; do
          case "$f" in
            .git/*|.rfg/*|*__pycache__*|.pytest_cache/*|.benchmarks/*) continue ;;
          esac
          # Verzeichnisse (Trailing /) rekursiv, Dateien direkt.
          if [ -d "$ROOT/$f" ]; then
            find "$ROOT/$f" -type f \
              -not -path "$ROOT/.git/*" -not -path "$ROOT/.rfg/*" \
              -not -path "*__pycache__/*" -not -path "$ROOT/.pytest_cache/*" \
              -not -path "$ROOT/.benchmarks/*" -exec cat {} + 2>/dev/null | wc -c
          elif [ -f "$ROOT/$f" ]; then
            wc -c <"$ROOT/$f"
          fi
        done | awk '{s+=$1} END {print s+0}'
  )
  echo $((diff_bytes + un_bytes))
}

classify() {
  local n=$1
  if [ "$n" -lt "$S_MAX" ]; then echo S
  elif [ "$n" -lt "$M_MAX" ]; then echo M
  elif [ "$n" -lt "$L_MAX" ]; then echo L
  else echo XL
  fi
}

gate_no_bypass() {
  # No-Bypass: Handoff vorhanden + frisch, sonst Abbruch (kein --force).
  [ -f "$HANDOFF" ] || fail ".handoff.md fehlt, kein switch-Paket moeglich"
  if [ -f "$ROOT/tools/verify_handoff.py" ]; then
    python3 "$ROOT/tools/verify_handoff.py" --check --root "$ROOT" >/dev/null \
      || fail "Handoff STALE (verify_handoff --check rot), neues Handoff anfordern"
  fi
}

diffstat_block() {
  {
    echo '--- status --short ---'
    git -C "$ROOT" status --short 2>/dev/null | head -n 20 || echo '(kein Status)'
    echo '--- diff --stat ---'
    git -C "$ROOT" diff --stat 2>/dev/null || echo '(kein diff: unborn HEAD oder Fehler)'
  }
}

build_packet() {
  # $1 = Klasse (M/L). S kommt hier nie an (skip). Cutoff nur bei Bedarf:
  # passt alles ins Budget, endet das Paket ohne CUTOFF-Marker (nur Suffix).
  local class=$1 budget sha full
  budget=$M_PAKET_CHARS
  [ "$class" = "M" ] || budget=$L_PAKET_CHARS
  sha=$(head_sha)
  full=$({
    echo "=== CTX:CORE:v1:START ==="
    cat "$AGENTS"
    echo "=== CTX:CORE:v1:END ==="
    echo "=== CTX:HANDOFF:v1:START ==="
    cat "$HANDOFF"
    echo "=== CTX:HANDOFF:v1:END ==="
    echo "=== CTX:POINTER:v1:START ==="
    echo "sha: $sha"
    echo "ampel: $class"
    diffstat_block
    echo "Empfaenger holt selbst: git show <SHA>:<path> (siehe docs/git-anchor.md)"
    echo "Step-0: SHA==HEAD + verify_handoff --check + pytest (siehe docs/verify-first.md)"
    echo "=== CTX:POINTER:v1:END ==="
  })
  if [ "${#full}" -gt "$budget" ]; then
    # head -c schliesst die Pipe frueh -> SIGPIPE upstream ist erwartet
    # (pipefail abfangen, sonst Exit 141 statt Paket).
    printf '%s' "$full" | head -c "$budget" || true
    # head -c schneidet ggf. mitten in der Zeile: Marker + Suffix als Abschluss.
    printf '\n... [CUTOFF ampel=%s budget=%s chars, Rest via git show]%s\n' "$class" "$budget" "$SWITCH_SUFFIX"
  else
    printf '%s%s\n' "$full" "$SWITCH_SUFFIX"
  fi
}

cmd_check() {
  gate_no_bypass
  local sha n class
  sha=$(head_sha)
  n=$(payload_bytes)
  class=$(classify "$n")
  echo "switch-check: ok (Gates gruen)"
  echo "sha: $sha"
  echo "delta: ${n} bytes -> ampel $class"
  if [ "$class" = "XL" ]; then
    echo "switch-check: WARN (XL >80k, Paket wird auf L-Budget gekappt)"
  fi
}

json_escape() {
  # Minimal JSON-Escape (SHA-Zeilen: keine Steuerzeichen erwartet).
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

ttl_remaining() {
  # Restsekunden bis gueltig_bis (Gates gruen -> nie negativ, Floor 0).
  local raw epoch now
  raw=$(grep -m1 -E '^[[:space:]]*gueltig_bis:' "$HANDOFF" | sed -E 's/^[^:]*:[[:space:]]*//')
  epoch=$(date -u -d "$raw" +%s 2>/dev/null) || { echo 0; return; }
  now=$(date -u +%s)
  if [ "$epoch" -gt "$now" ]; then echo $((epoch - now)); else echo 0; fi
}

cmd_json() {
  # $1 = erzwungene Klasse ("" = auto). Einzeiliges JSON. Caller hat Gates.
  local sha n class ttl forced=${1:-}
  sha=$(head_sha)
  n=$(payload_bytes)
  class=$(classify "$n")
  if [ -n "$forced" ]; then class="$forced"; fi  # Reduktions-Wahl, Gates bleiben.
  ttl=$(ttl_remaining)
  printf '{"tool":"switch_to_codex","ampel":"%s","delta_bytes":%d,"sha":"%s","handoff":"fresh","ttl_remaining_s":%d}\n' \
    "$class" "$n" "$(json_escape "$sha")" "$ttl"
}

main() {
  local size="" out="" auto=1 json=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --help|-h) usage; exit 0 ;;
      --check) cmd_check; exit 0 ;;
      --json) json=1; shift ;;
      --auto) auto=1; shift ;;
      --size) size="${2:?--size braucht S|M|L}"; auto=0; shift 2 ;;
      --size=*) size="${1#--size=}"; auto=0; shift ;;
      --out) out="${2:?--out braucht FILE}"; shift 2 ;;
      --out=*) out="${1#--out=}"; shift ;;
      *) fail "unbekannte Option: $1 (siehe --help)" ;;
    esac
  done
  case "$size" in ""|S|M|L) ;; *) fail "--size nur S|M|L" ;; esac

  gate_no_bypass
  local n class sha
  n=$(payload_bytes)
  class=$(classify "$n")
  if [ -n "$size" ]; then class="$size"; fi  # Reduktions-Wahl, Gates bleiben.

  if [ "$json" = 1 ]; then
    if [ -n "$out" ]; then
      cmd_json "$size" >"$out"
      echo "switch-json: ok (ampel $class -> $out)"
    else
      cmd_json "$size"
    fi
    exit 0
  fi

  if [ "$class" = "S" ]; then
    # S (auto oder --size S): skip, nur SHA-Zeile, kein Paket noetig.
    sha=$(head_sha)
    {
      if [ -n "$size" ]; then
        echo "switch-paket: SKIP (S erzwungen via --size S, delta ${n} bytes)"
      else
        echo "switch-paket: SKIP (S, delta ${n} bytes <5k, nur SHA noetig)"
      fi
      echo "sha: $sha"
      echo "resume: .handoff.md lesen, Step-0 (SHA==HEAD + Verify-gruen), weiter."
      printf '%s\n' "$SWITCH_SUFFIX"
    } | { if [ -n "$out" ]; then tee "$out"; else cat; fi; }
    exit 0
  fi
  if [ "$class" = "XL" ]; then
    echo "switch: WARN (XL delta ${n} bytes >80k, Cutoff auf L-Budget)" >&2
    class=L
  fi
  if [ -n "$out" ]; then
    build_packet "$class" >"$out"
    echo "switch-paket: ok (ampel $class, delta ${n} bytes -> $out)"
  else
    build_packet "$class"
  fi
}

main "$@"
