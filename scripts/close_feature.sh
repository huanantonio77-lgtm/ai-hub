#!/bin/bash
# s107-2: correct close procedure order.
# usage: bash scripts/close_feature.sh
set -u
cd "$(dirname "$0")/.." || exit 1

echo "[close] 1. heal (auto-sign / format / compile)"
python3 scripts/post_patch_heal.py

echo "[close] 2. session_verify --out"
python3 session_verify.py --out 2>&1 | grep -E "mode=|regression=" | head -3

echo "[close] done"
