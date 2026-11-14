#!/usr/bin/env bash
# Writes app/config.json for a CI build. Everything in a web page or APK is public, so it holds
# no keys: only where the encrypted data file is (DATA_URL; empty = data/data.json next to the
# web app) and the contact links.
set -euo pipefail

if [ -n "${DATA_URL:-}" ]; then
  case "$DATA_URL" in
    https://*) ;;
    *) echo "DATA_URL must start with https://" >&2; exit 1 ;;
  esac
fi

python3 - <<'PY'
import json, os
json.dump({
    "DATA_URL": os.environ.get("DATA_URL", ""),
    "BENCHMARK": "SPY",
    "LINKEDIN_URL": os.environ.get("LINKEDIN_URL", ""),
    "GITHUB_URL": "https://github.com/nsskn982",
}, open("config.json", "w"))
PY
echo "config.json written (DATA_URL=${DATA_URL:-data/data.json, next to the app})"
