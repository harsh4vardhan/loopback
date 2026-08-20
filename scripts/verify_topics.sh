#!/usr/bin/env bash
# Confirm the tag bar is live: the route answers, and filters actually filter.
B="${1:-https://loopback-production.up.railway.app}"

for _ in $(seq 1 30); do
  if curl -s -m 12 "$B/api/v1/topics" | grep -q '"topics"'; then
    echo "NEW BUILD LIVE"
    break
  fi
  sleep 10
done

echo
echo "--- chips ---"
curl -s -m 20 "$B/api/v1/topics?hours=48&limit=14" \
  | tr '{' '\n' | grep -oE '"tag": "[^"]*"|"kind": "[^"]*"|"count": [0-9]+' \
  | paste - - - 2>/dev/null | sed 's/^/  /'

echo
echo "--- feed filtered to youtube ---"
curl -s -m 20 "$B/api/v1/feed?limit=4&source=youtube" \
  | tr '{' '\n' | grep -oE '"source": "[^"]{0,18}|"caption": "[^"]{0,52}' | sed 's/^/  /'

echo
echo "--- feed filtered to gaming ---"
curl -s -m 20 "$B/api/v1/feed?limit=3&topic=gaming" \
  | tr '{' '\n' | grep -oE '"caption": "[^"]{0,58}' | sed 's/^/  /'

echo
echo "--- frontend has the bar? ---"
curl -s -m 20 "$B/" | grep -c 'id="topicbar"' | sed 's/^/  topicbar in shell: /'
curl -s -m 20 "$B/static/app.js" | grep -c 'renderTopicBar' | sed 's/^/  renderTopicBar in app.js: /'
