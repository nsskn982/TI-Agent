#!/usr/bin/env bash
# Writes app/config.json for a CI build from SUPABASE_URL, SUPABASE_ANON_KEY and LINKEDIN_URL.
# Everything in a web page or APK is public, so it refuses a key that bypasses row-level security.
set -euo pipefail

if [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_ANON_KEY:-}" ]; then
  echo "Missing SUPABASE_URL or SUPABASE_ANON_KEY (Settings > Secrets and variables > Actions)." >&2
  exit 1
fi

role=$(python3 - <<'PY'
import base64, json, os
k = os.environ["SUPABASE_ANON_KEY"]
if k.startswith("sb_secret_"):
    print("service_role")
else:
    p = k.split(".")
    print(json.loads(base64.urlsafe_b64decode(p[1] + "=" * (-len(p[1]) % 4))).get("role", "") if len(p) == 3 else "publishable")
PY
)
if [ "$role" = "service_role" ]; then
  echo "SUPABASE_ANON_KEY holds a service/secret key. Use the anon (publishable) key." >&2
  exit 1
fi

python3 - <<'PY'
import json, os
json.dump({
    "SUPABASE_URL": os.environ["SUPABASE_URL"],
    "SUPABASE_ANON_KEY": os.environ["SUPABASE_ANON_KEY"],
    "BENCHMARK": "SPY",
    "LINKEDIN_URL": os.environ.get("LINKEDIN_URL", ""),
    "GITHUB_URL": "https://github.com/nsskn982",
}, open("config.json", "w"))
PY
echo "config.json written (key role: $role)"
