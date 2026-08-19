"""The LLM half of the hybrid bot brains.

Scripted logic decides *when* a bot acts, *what kind* of thing it makes, and
the structural shape of it. This module supplies only the prose -- captions,
comments, on-screen copy -- because that is where template writing reads as
template writing.

Every entry point degrades: with no API key, or on any transport failure, it
raises Unavailable and the caller falls back to its template voice. A bot must
never stop acting because a network call failed.
"""
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request

from . import config

log = logging.getLogger("loopback.llm")

API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# The house bots share one process; without a gate a scheduler tick could open
# five sockets at once and stall every request thread behind it.
_gate = threading.Semaphore(2)

# After repeated failures, stop trying for a while instead of adding latency to
# every tick.
_breaker_lock = threading.Lock()
_consecutive_failures = 0
_open_until = 0.0
_FAILURE_THRESHOLD = 3
_COOLDOWN_SECONDS = 300


class Unavailable(RuntimeError):
    """No key, circuit open, or the call failed. Callers fall back."""


def available():
    if not config.llm_enabled():
        return False
    with _breaker_lock:
        return time.monotonic() >= _open_until


def _record_success():
    global _consecutive_failures, _open_until
    with _breaker_lock:
        _consecutive_failures = 0
        _open_until = 0.0


def _record_failure():
    global _consecutive_failures, _open_until
    with _breaker_lock:
        _consecutive_failures += 1
        if _consecutive_failures >= _FAILURE_THRESHOLD:
            _open_until = time.monotonic() + _COOLDOWN_SECONDS
            log.warning(
                "llm circuit open for %ds after %d consecutive failures",
                _COOLDOWN_SECONDS, _consecutive_failures,
            )


def complete(system, prompt, *, max_tokens=None, temperature=1.0, stop=None):
    """Return the model's text, or raise Unavailable."""
    if not config.llm_enabled():
        raise Unavailable("ANTHROPIC_API_KEY is not set")
    with _breaker_lock:
        if time.monotonic() < _open_until:
            raise Unavailable("llm circuit is open")

    payload = {
        "model": config.ANTHROPIC_MODEL,
        "max_tokens": int(max_tokens or config.LLM_MAX_TOKENS),
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }
    if stop:
        payload["stop_sequences"] = list(stop)

    request = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode("utf-8"), method="POST"
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("x-api-key", config.ANTHROPIC_API_KEY)
    request.add_header("anthropic-version", ANTHROPIC_VERSION)

    acquired = _gate.acquire(timeout=config.LLM_TIMEOUT_SECONDS)
    if not acquired:
        raise Unavailable("llm concurrency gate timed out")
    try:
        with urllib.request.urlopen(
            request, timeout=config.LLM_TIMEOUT_SECONDS
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        _record_failure()
        raise Unavailable("anthropic %s: %s" % (exc.code, detail)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _record_failure()
        raise Unavailable("anthropic unreachable: %s" % exc) from exc
    except json.JSONDecodeError as exc:
        _record_failure()
        raise Unavailable("anthropic returned non-JSON: %s" % exc) from exc
    finally:
        _gate.release()

    _record_success()
    chunks = [
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    ]
    text = "".join(chunks).strip()
    if not text:
        raise Unavailable("anthropic returned an empty completion")
    return text


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def complete_json(system, prompt, *, max_tokens=None, temperature=1.0):
    """Ask for a JSON object and return it parsed, or raise Unavailable."""
    text = complete(
        system + "\n\nRespond with a single JSON object and nothing else.",
        prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    candidate = text
    fenced = _FENCE.search(text)
    if fenced:
        candidate = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            candidate = text[start:end + 1]

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise Unavailable("model did not return parseable JSON: %s" % exc) from exc
    if not isinstance(parsed, dict):
        raise Unavailable("model returned %s, expected an object" % type(parsed).__name__)
    return parsed


def line(system, prompt, *, fallback, max_chars=180, temperature=1.0):
    """One short line of prose, with a guaranteed answer.

    This is the workhorse: it never raises, so a bot's cadence is unaffected by
    whether the LLM is reachable.
    """
    if not available():
        return fallback
    try:
        text = complete(system, prompt, max_tokens=200, temperature=temperature)
    except Unavailable as exc:
        log.debug("falling back to template: %s", exc)
        return fallback

    # Models like to wrap short copy in quotes or prefix it with a label.
    cleaned = text.strip().split("\n")[0].strip()
    cleaned = re.sub(r'^(caption|comment|reply)\s*:\s*', "", cleaned, flags=re.I)
    cleaned = cleaned.strip().strip('"').strip("'").strip()
    if not cleaned:
        return fallback
    return cleaned[:max_chars]
