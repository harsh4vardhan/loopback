#!/usr/bin/env bash
B="${1:-https://loopback-production.up.railway.app}"

echo "--- asset version served ---"
curl -s -m 20 "$B/" | grep -o 'app\.js?v=[a-f0-9]*'

echo
echo "--- frontend: does the deployed app.js render provenance? ---"
n="$(curl -s -m 20 "$B/static/app.js" | grep -c 'ctx.subject')"
echo "  ctx.subject occurrences: $n"

echo
echo "--- event verbs recorded ---"
curl -s -m 25 "$B/api/v1/events?limit=300" \
  | tr '{' '\n' | grep -o '"verb": "[a-z.]*"' | sort | uniq -c | sort -rn

echo
echo "--- any milestone posts yet? ---"
curl -s -m 20 "$B/api/v1/events?verb=milestone.posted&limit=20" | head -c 400
echo
