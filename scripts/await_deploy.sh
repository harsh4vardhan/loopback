#!/usr/bin/env bash
# Wait until the deployed build reports the multi-provider stats shape.
BASE="${1:-https://loopback-production.up.railway.app}"
for _ in $(seq 1 45); do
  body="$(curl -s -m 12 "$BASE/api/v1/stats")"
  if printf '%s' "$body" | grep -q 'providers'; then
    echo "NEW BUILD LIVE"
    printf '%s\n' "$body"
    exit 0
  fi
  sleep 8
done
echo "timed out; last response:"
printf '%s\n' "$body"
exit 1
