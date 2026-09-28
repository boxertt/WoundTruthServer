#!/usr/bin/env bash
# Adapter entry point for the publishable skills (老夏 §2 SK-05, §2 阻断项 P0 2026-09-20 21:07).
#
# This is the ONLY place in the repository that knows how a publishable skill runs. The skill is a
# NAME: it is checked against the `publishable/PLAN.lock` allowlist and a strict name syntax, and the
# manifest is resolved inside `publishable/` after a containment check — so a caller cannot use a
# path to choose its own scope. The snapshot arrives on stdin (the clinical path); a file path is
# accepted only with `--synthetic-fixture`, only inside `tests/fixtures/`, which is an evaluation
# entry point and not clinical. `run_publishable_skill.py` then calls the PRODUCTION implementation
# directly (`app.agent_runtime.dispatch`) and returns the internal slices unchanged; the publishable
# layer keeps no second implementation of any slice logic. Skill bodies therefore carry no endpoint,
# port, credential, patient identifier, private path or model name.
#
# Usage:
#   tools/run-woundtruth-skill.sh <publishable-skill-name> < snapshot.json      # clinical
#   tools/run-woundtruth-skill.sh <publishable-skill-name> --synthetic-fixture tests/fixtures/x.json
#   WOUNDTRUTH_SKILL_PYTHON=/path/to/python   # environment difference lives here, not in skills
set -euo pipefail

skill_name_re='^[a-z0-9]+(-[a-z0-9]+)*$'
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"          # code/backend
plan_lock="$here/publishable/PLAN.lock"
publishable_root="$(readlink -f "$here/publishable")"

fail() {  # fail closed, machine-readable, never a partial read
  printf '{"error":"%s","skill":"%s","detail":"%s"}\n' "$1" "${2:-}" "${3:-}"
  exit 2
}

SKILL="${1:-}"
if [ -z "$SKILL" ]; then
  fail skill_argument_missing "" "usage: run-woundtruth-skill.sh <publishable-skill-name>"
fi
shift

[[ "$SKILL" =~ $skill_name_re ]] || fail skill_name_invalid "$SKILL" "name syntax"
grep -qxF "  - $SKILL" "$plan_lock" || fail skill_not_allowed "$SKILL" "not in PLAN.lock"

skill_dir="$here/publishable/$SKILL"
manifest="$skill_dir/skill_manifest.yaml"
if [ -L "$skill_dir" ] || [ -L "$manifest" ]; then
  fail skill_manifest_outside_root "$SKILL" "symlink"
fi
[ -f "$manifest" ] || fail skill_manifest_missing "$SKILL" "manifest file absent"
resolved="$(readlink -f "$manifest")"
case "$resolved" in
  "$publishable_root"/*) ;;
  *) fail skill_manifest_outside_root "$SKILL" "outside publishable root" ;;
esac

# 公开仓库不带后端虚拟环境。生产树里若有 .venv 仍用它；否则用 python3。
# WOUNDTRUTH_SKILL_PYTHON 始终优先。
if [ -n "${WOUNDTRUTH_SKILL_PYTHON:-}" ]; then
  python_bin="$WOUNDTRUTH_SKILL_PYTHON"
elif [ -x "$here/.venv/bin/python" ]; then
  python_bin="$here/.venv/bin/python"
else
  python_bin="$(command -v python3)"
fi
exec "$python_bin" "$here/tools/run_publishable_skill.py" "$SKILL" "$@"
