"""Fail over to another model instead of straight to the word banks.

Two faults, and together they are why comments kept coming out generic.

line() asked its assigned provider and, on any failure, returned the template
fallback. It never tried a provider that was working. So the moment Gemini's
free tier hit its daily ceiling, three of five bots silently dropped to word
banks -- while OpenAI sat available, barely used, with the whole budget intact.

And the circuit breaker treated every failure the same. Its 300-second cooldown
is right for a timeout or a blip; it is useless against a quota that resets
tomorrow, because the provider comes back into rotation every five minutes,
fails again, and takes three more calls with it each time. A 429 marked
RESOURCE_EXHAUSTED now opens the circuit for an hour, so an exhausted provider
stops being offered rather than being rediscovered continuously.
"""
import pathlib

p = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "llm.py"
s = p.read_text(encoding="utf-8")

# --- a quota failure is not a blip ----------------------------------------
s = s.replace(
    '''_FAILURE_THRESHOLD = 3
_COOLDOWN_SECONDS = 300''',
    '''_FAILURE_THRESHOLD = 3
_COOLDOWN_SECONDS = 300
# A daily quota does not come back in five minutes. Reopening the circuit on
# the usual cooldown just rediscovers the same exhaustion every five minutes,
# burning three more calls each time.
_EXHAUSTED_COOLDOWN_SECONDS = 3600''',
)

s = s.replace(
    '''def _record_failure(provider):
    with _breaker_lock:
        state = _breaker(provider)
        state["failures"] += 1
        if state["failures"] >= _FAILURE_THRESHOLD:
            state["open_until"] = time.monotonic() + _COOLDOWN_SECONDS
            log.warning(
                "%s circuit open for %ds after %d failures",
                provider, _COOLDOWN_SECONDS, state["failures"],
            )''',
    '''def _record_failure(provider, *, exhausted=False):
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
            )''',
)

s = s.replace(
    '''    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        _record_failure(provider)
        raise Unavailable("%s %s: %s" % (provider, exc.code, detail)) from exc''',
    '''    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        # 429 covers both "slow down" and "you are done for today". Only the
        # latter should take the provider out of rotation for an hour.
        exhausted = exc.code == 429 and (
            "RESOURCE_EXHAUSTED" in detail or "exceeded your current quota" in detail
            or "insufficient_quota" in detail
        )
        _record_failure(provider, exhausted=exhausted)
        raise Unavailable("%s %s: %s" % (provider, exc.code, detail)) from exc''',
)

# --- try another model before giving up -----------------------------------
s = s.replace(
    '''def line(system, prompt, *, fallback, provider=None, max_chars=180,
         temperature=1.0):
    """One short line of prose, with a guaranteed answer.

    Never raises. Returns (text, provider_actually_used) so a caller can report
    honestly what wrote the words.
    """
    chosen = resolve(provider)
    if chosen == TEMPLATES:
        return fallback, TEMPLATES

    try:
        text = complete(
            system, prompt, provider=chosen, max_tokens=200, temperature=temperature
        )
    except Unavailable as exc:
        log.debug("%s fell back to templates: %s", chosen, exc)
        return fallback, TEMPLATES

    # Models like to wrap short copy in quotes or prefix it with a label.
    cleaned = text.strip().split("\\n")[0].strip()
    cleaned = _LABEL_PREFIX.sub("", cleaned)
    cleaned = cleaned.strip().strip('"').strip("'").strip()
    if not cleaned:
        return fallback, TEMPLATES
    return cleaned[:max_chars], chosen''',
    '''def _clean(text, max_chars):
    """Models like to wrap short copy in quotes or prefix it with a label."""
    cleaned = text.strip().split("\\n")[0].strip()
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
    return fallback, TEMPLATES''',
)

p.write_text(s, encoding="utf-8")
print("llm.py patched")
for marker in ("_EXHAUSTED_COOLDOWN_SECONDS", "exhausted=exhausted",
               "failed over to", "def _clean"):
    print("  %-30s %s" % (marker, "present" if marker in s else "MISSING"))
