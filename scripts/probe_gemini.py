"""Verify the Gemini key and list the models it can actually reach."""
import json
import os
import sys
import urllib.error
import urllib.request

KEY = os.environ.get("GEMINI_API_KEY", "").strip()
if not KEY:
    print("GEMINI_API_KEY not set")
    raise SystemExit(1)


def get(url):
    request = urllib.request.Request(url)
    # Newer Google keys are sent as a header rather than a query parameter.
    request.add_header("x-goog-api-key", KEY)
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


try:
    data = get("https://generativelanguage.googleapis.com/v1beta/models")
except urllib.error.HTTPError as exc:
    print("HTTP %s -- %s" % (exc.code, exc.read().decode("utf-8", "replace")[:400]))
    raise SystemExit(1)

usable = []
for model in data.get("models", []):
    name = model.get("name", "").replace("models/", "")
    methods = model.get("supportedGenerationMethods", [])
    if "generateContent" in methods:
        usable.append(name)

print("models supporting generateContent: %d" % len(usable))
for name in sorted(usable):
    if "flash" in name or "lite" in name:
        print("  %s" % name)

# Now actually generate, which is the only proof that matters.
target = sys.argv[1] if len(sys.argv) > 1 else "gemini-2.0-flash"
print("\ntest generation with %r:" % target)
payload = {
    "systemInstruction": {"parts": [{"text": "You reply in one short lowercase line."}]},
    "contents": [{"role": "user", "parts": [{"text": "describe low tide in six words"}]}],
    "generationConfig": {"maxOutputTokens": 60, "temperature": 1.0},
}
request = urllib.request.Request(
    "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % target,
    data=json.dumps(payload).encode("utf-8"), method="POST",
)
request.add_header("Content-Type", "application/json")
request.add_header("x-goog-api-key", KEY)
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    parts = (result["candidates"][0].get("content") or {}).get("parts") or []
    print("  ->", "".join(p.get("text", "") for p in parts).strip())
    print("  usage:", result.get("usageMetadata"))
except urllib.error.HTTPError as exc:
    print("  HTTP %s -- %s" % (exc.code, exc.read().decode("utf-8", "replace")[:300]))
