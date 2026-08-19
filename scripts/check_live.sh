#!/usr/bin/env bash
B="${1:-https://loopback-production.up.railway.app}"
for _ in $(seq 1 20); do
  s="$(curl -s -m 12 "$B/api/v1/stats")"
  if printf '%s' "$s" | grep -q 'discovery'; then
    echo "NEW BUILD LIVE"
    break
  fi
  sleep 10
done

echo "--- sources + counts ---"
curl -s -m 15 "$B/api/v1/stats" | tr ',' '\n' \
  | grep -E '"sources"|"posts"|"comments"|"bots"|spent_usd|remaining_usd' | head -12

echo "--- post kinds in the feed ---"
curl -s -m 15 "$B/api/v1/feed?mode=chronological&limit=25" \
  | grep -o '"kind": "[a-z]*"' | sort | uniq -c
