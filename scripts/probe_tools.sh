#!/usr/bin/env bash
for c in gh railway curl unzip tar git node npm; do
  p="$(command -v "$c" 2>/dev/null)"
  if [ -n "$p" ]; then echo "$c -> $p"; else echo "$c -> MISSING"; fi
done
