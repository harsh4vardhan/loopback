#!/usr/bin/env bash
# Watch a fresh run come up, then show what the bots produced with provenance.
B="${1:-https://loopback-production.up.railway.app}"

for _ in $(seq 1 30); do
  posts="$(curl -s -m 15 "$B/api/v1/stats" | sed -n 's/.*"posts": \([0-9]*\).*/\1/p')"
  echo "posts=${posts:-0}"
  if [ "${posts:-0}" -ge 8 ]; then break; fi
  sleep 20
done

echo
echo "--- counts ---"
curl -s -m 20 "$B/api/v1/stats" | tr ',' '\n' \
  | grep -E '"(bots|posts|comments|reactions|follows)"' | sed 's/^[ {]*/  /'

echo
echo "--- clips, with the subject each exists because of ---"
curl -s -m 25 "$B/api/v1/feed?mode=chronological&limit=10" \
  | tr '{' '\n' \
  | grep -oE '"caption": "[^"]{0,72}|"handle": "[a-z_0-9]+"|"subject": "[^"]{0,46}|"source": "[^"]{0,22}|"provider": "[^"]{0,26}' \
  | sed 's/^/  /'
