#!/usr/bin/env bash
# Compare the two services: which is serving, and which is posting.
NEW="https://loopback-web-production.up.railway.app"
OLD="https://loopback-production.up.railway.app"

for pair in "new:$NEW" "old:$OLD"; do
  name="${pair%%:*}"
  url="${pair#*:}"
  code="$(curl -s -o /dev/null -w '%{http_code}' -m 20 "$url/healthz")"
  echo "$name  $url  -> $code"
done

echo
echo "--- shared database counts ---"
curl -s -m 20 "$NEW/api/v1/stats" | tr ',' '\n' \
  | grep -E '"(bots|posts|comments|reactions)"' | sed 's/^[ {]*/  /'

echo
echo "--- sources live on new service ---"
curl -s -m 20 "$NEW/api/v1/stats" | tr '{' '\n' | grep -o '"sources": \[[^]]*\]' | sed 's/^/  /'

echo
echo "--- newest captions (shared db) ---"
curl -s -m 25 "$NEW/api/v1/feed?mode=chronological&limit=6" \
  | tr '{' '\n' \
  | grep -oE '"caption": "[^"]{0,84}|"handle": "[a-z_0-9]+"' | sed 's/^/  /'
