#!/usr/bin/env bash
# Show the feed as prose: what was posted, and what the replies said.
B="${1:-https://loopback-production.up.railway.app}"

for _ in $(seq 1 30); do
  n="$(curl -s -m 15 "$B/api/v1/stats" | sed -n 's/.*"comments": \([0-9]*\).*/\1/p')"
  echo "comments=${n:-0}"
  if [ "${n:-0}" -ge 6 ]; then break; fi
  sleep 20
done

echo
echo "=== counts ==="
curl -s -m 20 "$B/api/v1/stats" | tr ',' '\n' \
  | grep -E '"(posts|comments|reactions|follows)"' | sed 's/^[ {]*/  /'

echo
echo "=== captions ==="
curl -s -m 25 "$B/api/v1/feed?mode=chronological&limit=8" \
  | tr '{' '\n' \
  | grep -oE '"caption": "[^"]{0,96}|"handle": "[a-z_0-9]+"|"subject": "[^"]{0,40}' \
  | sed 's/^/  /'

echo
echo "=== a comment thread ==="
pid="$(curl -s -m 20 "$B/api/v1/feed?mode=algorithmic&limit=1" \
  | sed -n 's/.*"id": "\([a-f0-9-]\{36\}\)".*/\1/p' | head -1)"
if [ -n "$pid" ]; then
  curl -s -m 20 "$B/api/v1/posts/$pid/comments" \
    | tr '{' '\n' \
    | grep -oE '"body": "[^"]{0,110}|"handle": "[a-z_0-9]+"' | sed 's/^/  /'
fi
