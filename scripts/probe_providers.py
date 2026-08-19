"""Verify each provider key and list the models it actually offers.

Guessing model ids is how you get a 404 at 3am. This asks.
"""
import json
import os
import sys
import urllib.error
import urllib.request

ENDPOINTS = {
    "openai": ("https://api.openai.com/v1/models", "OPENAI_API_KEY"),
    "xai": ("https://api.x.ai/v1/models", "XAI_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1/models", "GROQ_API_KEY"),
}


def probe(name, url, env_name):
    key = os.environ.get(env_name, "").strip()
    if not key:
        print("%-9s no key in %s" % (name, env_name))
        return
    request = urllib.request.Request(url)
    request.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:200]
        print("%-9s HTTP %s -- %s" % (name, exc.code, body))
        return
    except Exception as exc:  # noqa: BLE001
        print("%-9s unreachable: %s" % (name, exc))
        return

    ids = sorted(item.get("id", "?") for item in (data.get("data") or []))
    print("%-9s OK, %d models" % (name, len(ids)))
    for model_id in ids[:40]:
        print("            %s" % model_id)


if __name__ == "__main__":
    for name, (url, env_name) in ENDPOINTS.items():
        if len(sys.argv) > 1 and name not in sys.argv[1:]:
            continue
        probe(name, url, env_name)
        print()
