#!/usr/bin/env bash
# Which GitHub Apps are installed on this account, and can they see the repo?
echo "=== installed apps ==="
gh api /user/installations --jq '.installations[] | "\(.id)\t\(.app_slug)\t\(.repository_selection)"' 2>&1 | head -20

echo
echo "=== repo visibility ==="
gh repo view harsh4vardhan/loopback --json name,visibility,url 2>&1 | head -10
