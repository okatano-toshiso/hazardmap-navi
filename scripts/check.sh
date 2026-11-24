#!/usr/bin/env bash
# Run every check: Hazard Map Navi tests + mock evaluation, then EDEN SYSTEM tests.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
uv run --frozen pytest -q
out="$(mktemp -t hinan-eval.XXXXXX)"
uv run --frozen python scripts/run_eval.py --provider mock --out "$out"
rm -f "$out"
(cd apps/eden-system && uv run --frozen pytest -q)
echo "all checks passed"
