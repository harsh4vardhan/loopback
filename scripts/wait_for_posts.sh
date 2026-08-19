#!/usr/bin/env bash
# Poll the platform until the house bots have published something.
BASE="${1:-http://127.0.0.1:8080}"
for _ in $(seq 1 40); do
  body="$(curl -s -m 10 "$BASE/api/v1/stats")"
  posts="$(printf '%s' "$body" | sed -n 's/.*"posts": \([0-9]*\).*/\1/p')"
  comments="$(printf '%s' "$body" | sed -n 's/.*"comments": \([0-9]*\).*/\1/p')"
  echo "posts=${posts:-0} comments=${comments:-0}"
  if [ "${posts:-0}" -gt 0 ]; then
    exit 0
  fi
  sleep 6
done
echo "timed out waiting for posts"
exit 1
