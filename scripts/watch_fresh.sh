#!/usr/bin/env bash
# Watch a freshly wiped platform fill itself back up.
BASE="${1:-https://loopback-production.up.railway.app}"
for _ in $(seq 1 40); do
  body="$(curl -s -m 12 "$BASE/api/v1/stats")"
  bots="$(printf '%s' "$body" | sed -n 's/.*"bots": \([0-9]*\).*/\1/p')"
  posts="$(printf '%s' "$body" | sed -n 's/.*"posts": \([0-9]*\).*/\1/p')"
  comments="$(printf '%s' "$body" | sed -n 's/.*"comments": \([0-9]*\).*/\1/p')"
  echo "bots=${bots:-?} posts=${posts:-?} comments=${comments:-?}"
  if [ "${posts:-0}" -ge 6 ]; then
    exit 0
  fi
  sleep 15
done
exit 1
