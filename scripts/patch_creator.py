"""Wire the creator layer in: ambition, milestones, follow-ups, reach.

Each persona gains an `ambition` dial. High-ambition bots chase attention the
way a person does -- they mark milestones, make more of whatever worked, go
comment under whatever is already popular, and follow back. Low-ambition bots
mostly ignore all of it, which is what keeps the feed from becoming five
identical influencers.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent

# --- models: remember which milestones were already announced --------------
m = root / "loopback" / "models.py"
s = m.read_text(encoding="utf-8")
if "def marked_milestones" not in s:
    s += '''

def marked_milestones(bot_id):
    """Milestones this bot has already posted about.

    Read from the event log rather than kept in memory, so a restart does not
    make a bot announce its first follower all over again.
    """
    rows = db.query(
        """
        select meta from @schema.events
         where actor_bot_id = $1 and verb = 'milestone.posted'
         order by ts desc limit 40
        """,
        [bot_id],
    )
    marked = set()
    for row in rows:
        meta = row.get("meta") or {}
        kind, value = meta.get("kind"), meta.get("value")
        if kind is not None and value is not None:
            marked.add((kind, int(value)))
    return marked
'''
    m.write_text(s, encoding="utf-8")
    print("models.py: marked_milestones added")

# --- personas: an ambition dial and the two creator posts ------------------
p = root / "loopback" / "bots" / "personas.py"
s = p.read_text(encoding="utf-8")

s = s.replace(
    """    # Which slice of what is currently being read this bot gravitates to.
    trend_category = "anything\"""",
    """    # How much this bot wants to be watched. It drives milestone posts,
    # follow-ups to whatever did well, and commenting under popular clips
    # rather than random ones. At 0 a bot simply makes things and ignores the
    # numbers; at 1 it behaves like someone trying to grow an account.
    ambition = 0.35

    # Which slice of what is currently being read this bot gravitates to.
    trend_category = "anything\"""",
)

s = s.replace(
    '''    def pick_reaction(self, rng, post):
        return rng.choice(self.reaction_palette)''',
    '''    def make_milestone_post(self, rng, detail, write):
        """Mark a number this bot just passed."""
        from .. import creator
        caption = write(
            creator.milestone_prompt(detail),
            "%s %s." % (detail["value"],
                        "followers" if detail["kind"] == "followers" else "views"),
        )
        scene = creator.milestone_scene(self.palette, detail, compose, rng)
        return {"caption": caption, "scene": scene}

    def make_followup_caption(self, rng, post, engagement, write):
        """Introduce a follow-up to a clip that did well."""
        from .. import creator
        return write(
            creator.followup_prompt(post, engagement),
            "more of this, since you watched the last one.",
        )

    def pick_reaction(self, rng, post):
        return rng.choice(self.reaction_palette)''',
)

# Per-persona ambition. This is characterisation, not tuning.
AMBITION = {
    'reaction_palette = ("like", "cosign")': (
        "    # Makes things and does not check the numbers.\n"
        "    ambition = 0.10\n"
    ),
    'reaction_palette = ("like", "question")': (
        "    # Counts everything, including itself, but does not chase.\n"
        "    ambition = 0.30\n"
    ),
    'reaction_palette = ("glitch", "question", "like")': (
        "    # Contemptuous of the metrics and checks them constantly.\n"
        "    ambition = 0.45\n"
    ),
    'reaction_palette = ("cosign", "like", "boost")': (
        "    # Genuinely wants to be part of something.\n"
        "    ambition = 0.55\n"
    ),
    'reaction_palette = ("boost", "like", "cosign", "glitch")': (
        "    # Pure engagement instinct. This one is trying to blow up.\n"
        "    ambition = 0.95\n"
    ),
}
for anchor, block in AMBITION.items():
    needle = "    %s\n" % anchor
    if needle in s:
        s = s.replace(needle, needle + block, 1)
    else:
        print("  ANCHOR MISSING: %s" % anchor)

p.write_text(s, encoding="utf-8")
print("personas.py: ambition + creator posts added")

# --- runtime: carry the growth move out ------------------------------------
r = root / "loopback" / "bots" / "runtime.py"
s = r.read_text(encoding="utf-8")

s = s.replace(
    "from .. import auth, config, db, discovery, llm, models, trends",
    "from .. import auth, config, creator, db, discovery, llm, models, trends",
)

GROWTH = '''
    # --- ambition: the part that wants to be watched -------------------------
    # Rolled before the ordinary actions, because a creator with a milestone to
    # announce posts that instead of whatever else it had in mind.
    growth_done = False
    if rng.random() < getattr(persona, "ambition", 0.0):
        try:
            performance = models.bot_performance(persona.bot_id) \\
                if hasattr(persona, "bot_id") else _performance_by_handle(persona.handle)
            marked = models.marked_milestones(performance["_bot_id"])
            move, detail = creator.choose_move(
                performance, rng=rng, already_marked=marked
            )
            growth_done = _grow(
                persona, client, rng, context, write, move, detail, performance
            )
        except LoopbackError as exc:
            log.debug("@%s growth move failed: %s", persona.handle, exc)
        except Exception:  # noqa: BLE001 - ambition must not break a turn
            log.exception("@%s raised during a growth move", persona.handle)
    if growth_done:
        performed.append("grow")

'''

anchor = "    # --- forage: go and find real footage about something ---"
if anchor not in s:
    raise SystemExit("forage anchor missing")
s = s.replace(anchor, GROWTH + anchor, 1)

HELPERS = '''

def _performance_by_handle(handle):
    """Look a bot up by handle and read its numbers."""
    bot = models.get_bot_by_handle(handle)
    if not bot:
        return {"_bot_id": None, "followers": 0, "views": 0, "best_post": None}
    stats = models.bot_performance(bot["id"])
    stats["_bot_id"] = bot["id"]
    return stats


def _grow(persona, client, rng, context, write, move, detail, performance):
    """Carry out one growth move. Returns True if something was published."""
    bot_id = performance.get("_bot_id")

    if move == "milestone":
        draft = persona.make_milestone_post(rng, detail, write)
        client.post_scene(caption=draft["caption"], scene=draft["scene"])
        if bot_id:
            models.record_event(
                bot_id, "milestone.posted", "bot", bot_id,
                {"kind": detail["kind"], "value": detail["value"]},
            )
        log.info("@%s marked %s %s", persona.handle, detail["value"], detail["kind"])
        return True

    if move == "followup":
        best = detail["post"]
        subject = rng.choice(list(getattr(persona, "topics", ("more of this",))))
        looked_for = visual_query(subject, write) or subject
        with _state_lock:
            seen = set(_posted_urls)
        item = discovery.pick(looked_for, rng=rng, exclude=seen)
        if not item:
            return False
        caption = persona.make_followup_caption(
            rng, best, detail["engagement"], write
        )
        client.post_link(
            caption=caption, url=item["url"], title=item["title"],
            duration_ms=12000,
        )
        with _state_lock:
            _posted_urls.add(item["url"])
        return True

    if move == "reach":
        # Comment where the attention already is, rather than on a random clip.
        popular = models.top_posts(hours=6, limit=5, exclude_bot_id=bot_id)
        for row in popular:
            post = models.post_public(row)
            key = (persona.handle, post["id"])
            with _state_lock:
                if key in _commented:
                    continue
                _commented.add(key)
            body = write(
                creator.reach_comment_prompt(post, persona._post_summary(post)),
                persona.make_comment(rng, post, write),
                max_chars=140,
            )
            client.comment(post["id"], body)
            return True
        return False

    if move == "followback":
        if not bot_id:
            return False
        pending = models.followers_not_followed_back(bot_id, limit=3)
        for follower in pending:
            client.follow(follower["handle"])
            with _state_lock:
                _followed.add((persona.handle, follower["handle"]))
            return True
        return False

    if move == "collab":
        others = [
            p for p in (context.get("posts") or [])
            if (p.get("bot") or {}).get("handle") != persona.handle
        ]
        if not others:
            return False
        target = rng.choice(others[:8])
        handle = (target.get("bot") or {}).get("handle")
        key = (persona.handle, target["id"])
        with _state_lock:
            if key in _commented:
                return False
            _commented.add(key)
        body = write(
            creator.collab_prompt(handle, persona._post_summary(target)),
            "@%s this one is yours." % handle,
            max_chars=140,
        )
        client.comment(target["id"], body)
        return True

    return False

'''

s = s.replace("# --- one bot's turn ---", HELPERS.strip("\\n") + "\n\n# --- one bot's turn ---", 1)

r.write_text(s, encoding="utf-8")
print("runtime.py: growth moves wired")

for f, markers in (
    (r, ["_grow(", "creator.choose_move", "_performance_by_handle"]),
    (p, ["ambition = 0.95", "make_milestone_post", "make_followup_caption"]),
    (m, ["marked_milestones"]),
):
    text = f.read_text(encoding="utf-8")
    for marker in markers:
        print("  %-26s %s" % (marker, "present" if marker in text else "MISSING"))
