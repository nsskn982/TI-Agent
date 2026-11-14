#!/usr/bin/env bash
# Writes app/config.json for a CI build from API_URL (the laptop's HTTPS tunnel) and LINKEDIN_URL.
# Everything in a web page or APK is public: only the API's address goes in, never a key.
set -euo pipefail

if [ -z "${API_URL:-}" ]; then
  echo "Missing API_URL (Settings > Secrets and variables > Actions > Variables), e.g. https://ti-agent.example.com" >&2
  exit 1
fi
case "$API_URL" in
  https://*) ;;
  *) echo "API_URL must start with https:// (the Cloudflare Tunnel hostname)." >&2; exit 1 ;;
esac

python3 - <<'PY'
import json, os
json.dump({
    "API_URL": os.environ["API_URL"].rstrip("/"),
    "BENCHMARK": "SPY",
    "LINKEDIN_URL": os.environ.get("LINKEDIN_URL", ""),
    "GITHUB_URL": "https://github.com/nsskn982",
}, open("config.json", "w"))
PY
echo "config.json written (API_URL=$API_URL)"
