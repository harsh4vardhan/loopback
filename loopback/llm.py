"""The prose half of the bot brains, across several providers.

Scripted logic decides *when* a bot acts and what shape its clip takes. This
module supplies only the words, and it does so through whichever provider that
bot is assigned. Different bots on different models is the point: it gives the
feed real variety, and it makes "powered by" on a profile a true statement
rather than decoration.

Three properties this file is built around:

  * **Always degradable.** `templates` is a provider like any other, and it is
    where every other provider falls back to. A bot never stops acting because
    a network call failed or a budget ran out.
  * **Metered.** Every call's tokens are recorded and costed. When the ledger
    passes LLM_BUDGET_USD, paid providers stop being offered and the population
    quietly drops to templates. A fixed budget cannot be overspent by a loop
    that runs unattended.
  * **Circuit broken.** Repeated failures on one provider take it out of
    rotation for a cooldown instead of adding latency to every tick.
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

# Prices are USD per 1M tokens, (input, output). They exist to keep a running
# estimate honest enough to stop on, not to reconcile a bill.
PRICING = {
    "openai": (0.10, 0.40),   # gpt-4.1-nano
    "xai": (0.30, 0.50),
    "anthropic": (1.00, 5.00),
    "groq": (0.0, 0.0),      # free tier
    "gemini": (0.0, 0.0),    # free tier
    "templates": (0.0, 0.0),
}

TEMPLATES = "templates"

_gate = threading.Semaphore(2)
_breaker_lock = threading.Lock()
_breakers = {}           # provider -> {"failures": n, "open_until": monotonic}
_FAILURE_THRESHOLD = 3
_COOLDOWN_SECONDS = 300
# A daily quota does not come back in five minutes. Reopening the circuit on
# the usual cooldown just rediscovers the same exhaustion every five minutes,
# burning three more calls each time.
_EXHAUSTED_COOLDOWN_SECONDS = 3600

_spend_lock = threading.Lock()
_spend_cache = {"usd": None, "checked_at": 0.0}
_SPEND_TTL = 60.0


class Unavailable(RuntimeError):
    """No credential, circuit open, budget spent, or the call failed."""


# --- provider definitions -------------------------------------------------

def _openai_compatible(base_url, api_key, model, system, prompt,
                       max_tokens, temperature):
    """OpenAI's chat-completions shape, which Groq also speaks."""
    payload = {
        "model": model,
        "max_tokens": int(max_tokens),
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        base_url, data=json.dumps(payload).encode("utf-8"), method="POST"
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", "Bearer " + api_key)

    with urllib.request.urlopen(request, timeout=config.LLM_TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    choices = data.get("choices") or []
    if not choices:
        raise Unavailable("provider returned no choices")
    text = (choices[0].get("message") or {}).get("content") or ""
    usage = data.get("usage") or {}
    return text.strip(), {
        "input": int(usage.get("prompt_tokens") or 0),
        "output": int(usage.get("completion_tokens") or 0),
    }


def _call_openai(system, prompt, max_tokens, temperature):
    return _openai_compatible(
        "https://api.openai.com/v1/chat/completions",
        config.OPENAI_API_KEY, config.OPENAI_MODEL,
        system, prompt, max_tokens, temperature,
    )


def _call_groq(system, prompt, max_tokens, temperature):
    return _openai_compatible(
        "https://api.groq.com/openai/v1/chat/completions",
        config.GROQ_API_KEY, config.GROQ_MODEL,
        system, prompt, max_tokens, temperature,
    )


def _call_xai(system, prompt, max_tokens, temperature):
    # xAI speaks the OpenAI chat-completions shape.
    return _openai_compatible(
        "https://api.x.ai/v1/chat/completions",
        config.XAI_API_KEY, config.XAI_MODEL,
        system, prompt, max_tokens, temperature,
    )


def _call_anthropic(system, prompt, max_tokens, temperature):
    payload = {
        "model": config.ANTHROPIC_MODEL,
        "max_tokens": int(max_tokens),
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"), method="POST",
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("x-api-key", config.ANTHROPIC_API_KEY)
    request.add_header("anthropic-version", "2023-06-01")

    with urllib.request.urlopen(request, timeout=config.LLM_TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    text = "".join(
        block.get("text", "") for block in data.get("content", [])
        if block.get("type") == "text"
    )
    usage = data.get("usage") or {}
    return text.strip(), {
        "input": int(usage.get("input_tokens") or 0),
        "output": int(usage.get("output_tokens") or 0),
    }


def _call_gemini(system, prompt, max_tokens, temperature):
    # The key goes in a header, not the query string: a URL with a
    # credential in it ends up in proxy logs and error reports.
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "%s:generateContent" % config.GEMINI_MODEL
    )
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": int(max_tokens),
            "temperature": temperature,
        },
    }
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST"
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("x-goog-api-key", config.GEMINI_API_KEY)

    with urllib.request.urlopen(request, timeout=config.LLM_TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    candidates = data.get("candidates") or []
    if not candidates:
        raise Unavailable("gemini returned no candidates")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts)
    usage = data.get("usageMetadata") or {}
    return text.strip(), {
        "input": int(usage.get("promptTokenCount") or 0),
        "output": int(usage.get("candidatesTokenCount") or 0),
    }


PROVIDERS = {
    "openai": {
        "call": _call_openai,
        "key": lambda: config.OPENAI_API_KEY,
        "model": lambda: config.OPENAI_MODEL,
        "label": lambda: "OpenAI %s" % config.OPENAI_MODEL,
        "paid": True,
    },
    "anthropic": {
        "call": _call_anthropic,
        "key": lambda: config.ANTHROPIC_API_KEY,
        "model": lambda: config.ANTHROPIC_MODEL,
        "label": lambda: "Anthropic %s" % config.ANTHROPIC_MODEL,
        "paid": True,
    },
    "xai": {
        "call": _call_xai,
        "key": lambda: config.XAI_API_KEY,
        "model": lambda: config.XAI_MODEL,
        "label": lambda: "xAI %s" % config.XAI_MODEL,
        "paid": True,
    },
    "groq": {
        "call": _call_groq,
        "key": lambda: config.GROQ_API_KEY,
        "model": lambda: config.GROQ_MODEL,
        "label": lambda: "Groq %s" % config.GROQ_MODEL,
        "paid": False,
    },
    "gemini": {
        "call": _call_gemini,
        "key": lambda: config.GEMINI_API_KEY,
        "model": lambda: config.GEMINI_MODEL,
        "label": lambda: "Google %s" % config.GEMINI_MODEL,
        "paid": False,
    },
    TEMPLATES: {
        "call": None,
        "key": lambda: "n/a",
        "model": lambda: "word banks",
        "label": lambda: "hand-written word banks",
        "paid": False,
    },
}


# --- budget ---------------------------------------------------------------

def spent_usd(*, force=False):
    """Estimated spend so far, cached briefly to keep ticks cheap."""
    now = time.monotonic()
    with _spend_lock:
        fresh = (not force
                 and _spend_cache["usd"] is not None
                 and now - _spend_cache["checked_at"] < _SPEND_TTL)
        if fresh:
            return _spend_cache["usd"]

    total = 0.0
    try:
        from . import db
        row = db.query_one(
            "select coalesce(sum(est_cost_usd), 0) as usd from @schema.llm_usage"
        )
        total = float((row or {}).get("usd") or 0.0)
    except Exception as exc:  # noqa: BLE001 - accounting must not break a tick
        log.debug("could not read llm spend: %s", exc)
        total = _spend_cache["usd"] or 0.0

    with _spend_lock:
        _spend_cache["usd"] = total
        _spend_cache["checked_at"] = now
    return total


def budget_remaining():
    if config.LLM_BUDGET_USD <= 0:
        return float("inf")
    return max(0.0, config.LLM_BUDGET_USD - spent_usd())


def _record_usage(provider, model, usage):
    rate_in, rate_out = PRICING.get(provider, (0.0, 0.0))
    cost = (usage["input"] * rate_in + usage["output"] * rate_out) / 1_000_000.0
    try:
        from . import db
        db.execute(
            """
            insert into @schema.llm_usage
                (provider, model, calls, input_tokens, output_tokens, est_cost_usd)
            values ($1, $2, 1, $3, $4, $5)
            """,
            [provider, model, usage["input"], usage["output"], cost],
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("could not record llm usage: %s", exc)

    with _spend_lock:
        if _spend_cache["usd"] is not None:
            _spend_cache["usd"] += cost
    return cost


# --- circuit breaker ------------------------------------------------------

def _breaker(provider):
    return _breakers.setdefault(provider, {"failures": 0, "open_until": 0.0})


def _record_success(provider):
    with _breaker_lock:
        state = _breaker(provider)
        state["failures"] = 0
        state["open_until"] = 0.0


def _record_failure(provider, *, exhausted=False):
    with _breaker_lock:
        state = _breaker(provider)
        state["failures"] += 1
        if exhausted:
            # Out of quota: stop offering it at all until well after a reset.
            state["open_until"] = time.monotonic() + _EXHAUSTED_COOLDOWN_SECONDS
            log.warning(
                "%s out of quota; withdrawn for %d minutes",
                provider, _EXHAUSTED_COOLDOWN_SECONDS // 60,
            )
        elif state["failures"] >= _FAILURE_THRESHOLD:
            state["open_until"] = time.monotonic() + _COOLDOWN_SECONDS
            log.warning(
                "%s circuit open for %ds after %d failures",
                provider, _COOLDOWN_SECONDS, state["failures"],
            )


def available(provider):
    """Can this provider be called right now?"""
    if provider == TEMPLATES:
        return True
    spec = PROVIDERS.get(provider)
    if not spec or not spec["key"]():
        return False
    if spec["paid"] and budget_remaining() <= 0:
        return False
    with _breaker_lock:
        return time.monotonic() >= _breaker(provider)["open_until"]


def resolve(provider):
    """The provider that will actually be used, after keys and budget."""
    if provider and available(provider):
        return provider
    # Prefer a free provider over silently spending, then fall to templates.
    for candidate in ("groq", "gemini", "openai", "xai", "anthropic"):
        if candidate != provider and available(candidate):
            return candidate
    return TEMPLATES


def label(provider):
    """The 'powered by' string for a bot on this provider."""
    spec = PROVIDERS.get(provider) or PROVIDERS[TEMPLATES]
    return spec["label"]()


def enabled_providers():
    return sorted(name for name in PROVIDERS if available(name))


# --- calling --------------------------------------------------------------

def complete(system, prompt, *, provider, max_tokens=None, temperature=1.0):
    """Raw completion against one provider. Raises Unavailable on any failure."""
    if provider == TEMPLATES:
        raise Unavailable("templates provider has no completion endpoint")

    spec = PROVIDERS.get(provider)
    if not spec:
        raise Unavailable("unknown provider %r" % provider)
    if not spec["key"]():
        raise Unavailable("%s has no API key configured" % provider)
    if spec["paid"] and budget_remaining() <= 0:
        raise Unavailable(
            "the $%.2f LLM budget is spent" % config.LLM_BUDGET_USD
        )
    with _breaker_lock:
        if time.monotonic() < _breaker(provider)["open_until"]:
            raise Unavailable("%s circuit is open" % provider)

    if not _gate.acquire(timeout=config.LLM_TIMEOUT_SECONDS):
        raise Unavailable("llm concurrency gate timed out")
    try:
        text, usage = spec["call"](
            system, prompt,
            int(max_tokens or config.LLM_MAX_TOKENS), temperature,
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        # 429 covers both "slow down" and "you are done for today". Only the
        # latter should take the provider out of rotation for an hour.
        exhausted = exc.code == 429 and (
            "RESOURCE_EXHAUSTED" in detail or "exceeded your current quota" in detail
            or "insufficient_quota" in detail
        )
        _record_failure(provider, exhausted=exhausted)
        raise Unavailable("%s %s: %s" % (provider, exc.code, detail)) from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        _record_failure(provider)
        raise Unavailable("%s unreachable: %s" % (provider, exc)) from exc
    finally:
        _gate.release()

    if not text:
        _record_failure(provider)
        raise Unavailable("%s returned an empty completion" % provider)

    _record_success(provider)
    _record_usage(provider, spec["model"](), usage)
    return text


_LABEL_PREFIX = re.compile(r'^(caption|comment|reply|line|output)\s*:\s*', re.I)


def _clean(text, max_chars):
    """Models like to wrap short copy in quotes or prefix it with a label."""
    cleaned = text.strip().split("\n")[0].strip()
    cleaned = _LABEL_PREFIX.sub("", cleaned)
    cleaned = cleaned.strip().strip('"').strip("'").strip()
    return cleaned[:max_chars] if cleaned else ""


def line(system, prompt, *, fallback, provider=None, max_chars=180,
         temperature=1.0):
    """One short line of prose, with a guaranteed answer.

    Tries the assigned provider, then any other provider that is available,
    and only then the word banks. Dropping straight to templates on the first
    failure is what made a single exhausted free tier silently flatten most of
    the population's writing while a working provider sat unused.

    Never raises. Returns (text, provider_actually_used) so a caller can report
    honestly what wrote the words.
    """
    chosen = resolve(provider)
    if chosen == TEMPLATES:
        return fallback, TEMPLATES

    # The assigned provider first, then whatever else can answer. Free before
    # paid, so a failover does not quietly start spending.
    order = [chosen] + [
        name for name in ("groq", "gemini", "openai", "xai", "anthropic")
        if name != chosen and available(name)
    ]

    for candidate in order:
        try:
            text = complete(
                system, prompt, provider=candidate,
                max_tokens=200, temperature=temperature,
            )
        except Unavailable as exc:
            log.debug("%s could not answer (%s)", candidate, exc)
            continue

        cleaned = _clean(text, max_chars)
        if cleaned:
            if candidate != chosen:
                log.info("%s failed over to %s", chosen, candidate)
            return cleaned, candidate

    log.warning("every provider declined; using the word banks")
    return fallback, TEMPLATES


def status():
    """For /api/v1/stats and the boot log."""
    return {
        "providers": {
            name: {
                "configured": bool(spec["key"]()),
                "available": available(name),
                "model": spec["model"](),
                "paid": spec["paid"],
            }
            for name, spec in PROVIDERS.items()
        },
        "budget_usd": config.LLM_BUDGET_USD or None,
        "spent_usd": round(spent_usd(), 4),
        "remaining_usd": (
            None if config.LLM_BUDGET_USD <= 0 else round(budget_remaining(), 4)
        ),
    }
