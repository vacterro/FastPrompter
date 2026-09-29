#!/usr/bin/env bash
# T-1350 conformance reverify sweep.
#
# One DONE ticket per line: <id>\t<test files>. Each ticket gets an EXECUTED
# reverify (--run), because the validator refuses an attested-only receipt:
# executed evidence is what makes it closure authority.
#
# The CLI prints `key: value` lines, not JSON -- parse that, not a JSON shape.
# Records ticket / result / receipt so nothing is marked verified on trust.
set -u
cd "V:\\\\___VAC\\\\__K\\\\__CODE\\\\_PY\\\\_FastPrompter" || exit 1
SAIPEN="C:/Users/vac34/.agents/skills/saipen/tools/saipen.py"
LOG=".saipen/evidence/t1350_sweep_results.tsv"
MAP=".saipen/evidence/t1350_sweep_map.tsv"
: > "$LOG"

while IFS=$'\t' read -r tid files; do
  [ -z "$tid" ] && continue
  if [ "$files" = "ALL" ]; then
    cmd="python -m pytest tests -q"
  else
    cmd="python -m pytest $files -q"
  fi
  out=$(python "$SAIPEN" work reverify "$tid" --run "$cmd" 2>&1 | tr -d '\r')
  code=$(printf '%s\n' "$out" | grep -o '^code: [A-Z_]*' | head -1 | cut -d' ' -f2)
  rcpt=$(printf '%s\n' "$out" | grep -o '^receipt_id: [A-Za-z0-9-]*' | head -1 | cut -d' ' -f2)
  if [ -z "$code" ]; then
    code=$(printf '%s\n' "$out" | head -2 | tr '\n' ' ' | cut -c1-90)
  fi
  printf '%s\t%s\t%s\t%s\n' "$tid" "${code:-NONE}" "${rcpt:--}" "$files" >> "$LOG"
  echo "$tid ${code:-NONE}"
done < "$MAP"
echo "--- sweep finished: $(wc -l < "$LOG") tickets ---"
