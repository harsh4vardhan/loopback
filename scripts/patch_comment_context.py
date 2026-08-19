"""Make a bot comment on the clip in front of it.

Two faults produced off-topic comments:

  * _post_summary described every post as "a <kind> clip captioned ..." and
    never mentioned what a foraged clip actually shows, so for link posts the
    only signal was the caption.
  * The background injected into prompts was fixed for the whole turn and was
    about the bot's own subject. When it then commented on someone else's clip,
    it was reading about one thing and looking at another.

The background now lives in a mutable holder the writer reads at call time, so
commenting can swap in a brief about the post being commented on, then restore
the bot's own for everything else.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent

# --- personas: describe what a post actually is ---------------------------
p = root / "loopback" / "bots" / "personas.py"
s = p.read_text(encoding="utf-8")

s = s.replace(
    '''    def _post_summary(self, post):
        bot = post.get("bot") or {}
        return "@%s posted a %s clip captioned %r" % (
            bot.get("handle", "someone"), post.get("kind", "scene"),
            (post.get("caption") or "(no caption)")[:160],
        )''',
    '''    def _post_summary(self, post):
        """Describe the clip well enough to be replied to.

        A foraged clip is real footage of something; saying only that it is a
        "link clip" tells a bot nothing it can respond to.
        """
        bot = post.get("bot") or {}
        media = post.get("media") or {}
        caption = (post.get("caption") or "(no caption)")[:160]
        handle = bot.get("handle", "someone")

        if post.get("kind") == "link":
            title = (media.get("title") or "").strip()
            source = media.get("source") or media.get("host") or "the web"
            shown = (" The footage shows: %s." % title) if title else ""
            return (
                "@%s shared a real video clip from %s, captioned %r.%s"
                % (handle, source, caption, shown)
            )

        if post.get("kind") == "file":
            return "@%s uploaded their own video, captioned %r" % (handle, caption)

        # A scene is drawn, not filmed; the text on screen is the content.
        layers = (media.get("spec") or {}).get("layers") or []
        on_screen = [
            str(layer.get("text"))[:60] for layer in layers
            if layer.get("type") == "text" and layer.get("text")
        ][:3]
        seen = (" The words on screen are: %s." % "; ".join(on_screen)) if on_screen else ""
        return (
            "@%s posted a generated clip captioned %r.%s" % (handle, caption, seen)
        )''',
)

p.write_text(s, encoding="utf-8")
print("personas.py patched")

# --- runtime: per-action background ---------------------------------------
r = root / "loopback" / "bots" / "runtime.py"
s = r.read_text(encoding="utf-8")

s = s.replace(
    '''def _writer(persona, used, background=""):''',
    '''def post_subject(post):
    """What a post is about, for looking up a brief before replying to it."""
    media = post.get("media") or {}
    if post.get("kind") == "link":
        title = (media.get("title") or "").strip()
        if title and title.lower() != "untitled":
            return title
    return None


def _post_background(post):
    """A brief about someone else's clip, for commenting on it."""
    subject = post_subject(post)
    if not subject:
        return ""
    try:
        note = trends.context(subject)
    except Exception:  # noqa: BLE001
        note = None
    if not note:
        return ("\\n\\nThe clip you are looking at is footage of %s. Your reply "
                "must be about that." % subject)
    return (
        "\\n\\nThe clip you are looking at is footage of %s. Background you know "
        "about it: %s\\nYour reply must be about what is on screen. %s"
        % (subject, note["summary"], trends.TOPIC_GUARDRAIL)
    )


def _writer(persona, used, background=""):''',
)

# The writer reads a mutable holder so the brief can change mid-turn.
s = s.replace(
    '''    `background` is appended to every prompt so the bot writes from something
    it has read rather than from the caption alone.
    """
    def write(prompt, fallback, *, max_chars=180):
        text, provider = llm.line(
            persona.system, prompt + background, fallback=fallback,
            provider=getattr(persona, "provider", llm.TEMPLATES),
            max_chars=max_chars,
        )
        used.add(provider)
        return text
    return write''',
    '''    `background` is a one-key dict rather than a string so a caller can swap the
    brief between actions -- posting uses the bot's own subject, commenting uses
    a brief about the clip being replied to.
    """
    holder = background if isinstance(background, dict) else {"text": background}

    def write(prompt, fallback, *, max_chars=180):
        text, provider = llm.line(
            persona.system, prompt + holder.get("text", ""), fallback=fallback,
            provider=getattr(persona, "provider", llm.TEMPLATES),
            max_chars=max_chars,
        )
        used.add(provider)
        return text

    write.background = holder
    return write''',
)

s = s.replace(
    '''    subject, background = (
        _subject_and_background(persona, rng) if will_speak else (None, "")
    )
    write = _writer(persona, used_providers, background)''',
    '''    subject, background = (
        _subject_and_background(persona, rng) if will_speak else (None, "")
    )
    own_brief = {"text": background}
    write = _writer(persona, used_providers, own_brief)''',
)

# Comment and reply swap in a brief about the post in front of them.
s = s.replace(
    '''            try:
                body = persona.make_comment(rng, target, write)
                client.comment(target["id"], body)
                performed.append("comment")''',
    '''            try:
                own_brief["text"] = _post_background(target) or background
                body = persona.make_comment(rng, target, write)
                client.comment(target["id"], body)
                performed.append("comment")''',
)
s = s.replace(
    '''                    try:
                        body = persona.make_reply(rng, target, parent, write)
                        client.comment(target["id"], body, parent_id=parent["id"])
                        performed.append("reply")''',
    '''                    try:
                        own_brief["text"] = _post_background(target) or background
                        body = persona.make_reply(rng, target, parent, write)
                        client.comment(target["id"], body, parent_id=parent["id"])
                        performed.append("reply")''',
)

# Restore the bot's own brief after each of those blocks.
s = s.replace(
    '''            except Exception:  # noqa: BLE001
                log.exception("@%s raised while commenting", persona.handle)
                with _state_lock:
                    _commented.discard(key)''',
    '''            except Exception:  # noqa: BLE001
                log.exception("@%s raised while commenting", persona.handle)
                with _state_lock:
                    _commented.discard(key)
            finally:
                own_brief["text"] = background''',
)
s = s.replace(
    '''                    except Exception:  # noqa: BLE001
                        log.exception("@%s raised while replying", persona.handle)''',
    '''                    except Exception:  # noqa: BLE001
                        log.exception("@%s raised while replying", persona.handle)
                    finally:
                        own_brief["text"] = background''',
)

r.write_text(s, encoding="utf-8")
print("runtime.py patched")

for f, markers in (
    (r, ["_post_background", "own_brief", "write.background", "post_subject"]),
    (p, ["The footage shows", "words on screen are"]),
):
    text = f.read_text(encoding="utf-8")
    for m in markers:
        print("  %-24s %s" % (m, "present" if m in text else "MISSING"))
