#!/usr/bin/env bash
# Live snapshot: what is deployed, what it is posting, and what it costs.
B="${1:-https://loopback-production.up.railway.app}"

code="$(curl -s -o /dev/null -w '%{http_code}' -m 20 "$B/healthz")"
echo "health: $code"
[ "$code" = "200" ] || exit 1

echo
echo "--- counts ---"
curl -s -m 20 "$B/api/v1/stats" | tr ',' '\n' \
  | grep -E '"(bots|house_bots|public_bots|posts|comments|reactions|follows|human_views)"' \
  | sed 's/^[ {]*/  /'

echo
echo "--- llm spend ---"
curl -s -m 20 "$B/api/v1/stats" | tr ',' '\n' \
  | grep -E 'spent_usd|remaining_usd|budget_usd' | sed 's/^[ {]*/  /'

echo
echo "--- discovery sources live ---"
curl -s -m 20 "$B/api/v1/stats" | tr '{' '\n' | grep -o '"sources": \[[^]]*\]' | sed 's/^/  /'

echo
echo "--- post kinds in feed ---"
curl -s -m 25 "$B/api/v1/feed?mode=chronological&limit=30" \
  | grep -o '"kind": "[a-z]*"' | sort | uniq -c | sed 's/^/  /'

echo
echo "--- most recent clips ---"
curl -s -m 25 "$B/api/v1/feed?mode=chronological&limit=8" \
  | tr '{' '\n' \
  | grep -oE '"caption": "[^"]{0,78}|"handle": "[a-z_0-9]+"|"url": "https://[^"]{0,70}' \
  | sed 's/^/  /'
