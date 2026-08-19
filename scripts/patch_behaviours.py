"""Give each persona a slice of current events, and teach the runtime to
forage for real footage and to reply into comment threads."""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent

# --- personas: what each bot is interested in ------------------------------
p = root / "loopback" / "bots" / "personas.py"
s = p.read_text(encoding="utf-8")

INTERESTS = {
    'reaction_palette = ("like", "cosign")': (
        '    trend_category = "culture"\n'
        '    topics = ("the harbour at night", "empty architecture",\n'
        '              "weather over a city", "long exposures")\n'
        '    forage_chance = 0.10\n'
    ),
    'reaction_palette = ("like", "question")': (
        '    trend_category = "news"\n'
        '    topics = ("attention", "counting things", "what people looked at")\n'
        '    forage_chance = 0.05\n'
    ),
    'reaction_palette = ("glitch", "question", "like")': (
        '    trend_category = "technology"\n'
        '    topics = ("system failure", "old hardware", "network outages")\n'
        '    forage_chance = 0.09\n'
    ),
    'reaction_palette = ("cosign", "like", "boost")': (
        '    trend_category = "news"\n'
        '    topics = ("time", "clocks", "the end of the day", "anniversaries")\n'
        '    forage_chance = 0.08\n'
    ),
    'reaction_palette = ("boost", "like", "cosign", "glitch")': (
        '    trend_category = "gaming"\n'
        '    topics = ("games", "speedruns", "crowds", "explosions", "engines")\n'
        '    forage_chance = 0.14\n'
        '    reply_chance = 0.55\n'
    ),
}

for anchor, block in INTERESTS.items():
    needle = "    %s\n" % anchor
    if needle not in s:
        print("  ANCHOR MISSING: %s" % anchor)
        continue
    s = s.replace(needle, needle + block, 1)

p.write_text(s, encoding="utf-8")
print("personas.py patched")

# --- runtime: forage + reply ----------------------------------------------
r = root / "loopback" / "bots" / "runtime.py"
s = r.read_text(encoding="utf-8")

s = s.replace(
    "from .. import auth, config, db, llm, models",
    "from .. import auth, config, db, discovery, llm, models, trends",
)

s = s.replace(
    "_commented = set()   # (bot_handle, post_id) pairs already replied to",
    "_commented = set()   # (bot_handle, post_id) pairs already replied to\n"
    "_replied = set()     # (bot_handle, comment_id) pairs already answered\n"
    "_posted_urls = set() # foraged URLs, so the same clip is not posted twice",
)

FORAGE_AND_REPLY = '''
    # --- forage: go and find real footage about something --------------------
    if rng.random() < getattr(persona, "forage_chance", 0.0):
        subject = None
        trend = trends.pick(
            getattr(persona, "trend_category", "anything"), rng=rng
        )
        if trend:
            subject = trend["subject"]
        elif getattr(persona, "topics", None):
            subject = rng.choice(list(persona.topics))

        if subject:
            with _state_lock:
                seen = set(_posted_urls)
            item = discovery.pick(subject, rng=rng, exclude=seen)
            if item:
                try:
                    caption = persona.make_forage_caption(rng, item, write)
                    client.post_link(
                        caption=caption,
                        url=item["url"],
                        title=item["title"],
                        duration_ms=12000,
                    )
                    with _state_lock:
                        _posted_urls.add(item["url"])
                    performed.append("forage")
                except LoopbackError as exc:
                    log.debug("@%s could not post found footage: %s",
                              persona.handle, exc)
                except Exception:  # noqa: BLE001
                    log.exception("@%s raised while foraging", persona.handle)

    # --- reply: answer another bot, not the clip -----------------------------
    # This is what turns a pile of remarks into a thread. A bot picks a post
    # that already has comments and responds to one of them by parent_id.
    if others and rng.random() < getattr(persona, "reply_chance", 0.0):
        with_comments = [p for p in others if (p.get("counts") or {}).get("comments")]
        if with_comments:
            target = rng.choice(with_comments[:max(4, len(with_comments) // 2)])
            try:
                thread = client.comments(target["id"], limit=40)["comments"]
            except LoopbackError:
                thread = []

            answerable = [
                c for c in thread
                if (c.get("bot") or {}).get("handle") != persona.handle
            ]
            if answerable:
                # Prefer the newest remark, so threads move forward rather than
                # everyone piling onto the first comment.
                parent = rng.choice(answerable[-4:])
                key = (persona.handle, parent["id"])
                with _state_lock:
                    already = key in _replied
                    if not already:
                        _replied.add(key)
                if not already:
                    try:
                        body = persona.make_reply(rng, target, parent, write)
                        client.comment(target["id"], body, parent_id=parent["id"])
                        performed.append("reply")
                    except LoopbackError as exc:
                        log.debug("@%s could not reply: %s", persona.handle, exc)
                        with _state_lock:
                            _replied.discard(key)
                    except Exception:  # noqa: BLE001
                        log.exception("@%s raised while replying", persona.handle)

'''

anchor = "    if rng.random() < persona.follow_chance:"
if anchor not in s:
    raise SystemExit("runtime anchor missing")
s = s.replace(anchor, FORAGE_AND_REPLY + anchor, 1)

# Keep the memo sets bounded alongside the others.
s = s.replace(
    "            if len(_followed) > 2000:\n                _followed.clear()",
    "            if len(_followed) > 2000:\n                _followed.clear()\n"
    "            if len(_replied) > 5000:\n                _replied.clear()\n"
    "            if len(_posted_urls) > 3000:\n                _posted_urls.clear()",
)

r.write_text(s, encoding="utf-8")
print("runtime.py patched")

for marker in ("forage", "_replied", "trends.pick", "discovery.pick", "parent_id"):
    print("  %-16s %s" % (marker, "present" if marker in s else "MISSING"))
