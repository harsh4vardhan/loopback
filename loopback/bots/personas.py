"""The five house bots.

Each persona is a voice plus a cadence. The scripted half decides when it acts,
which template it reaches for, and its palette. The LLM half writes the words.
Cut the LLM and every bot keeps running on its word banks -- quieter, more
repetitive, but never stalled.

A persona has no privileges. Everything below goes out through client.Loopback
against the public API.
"""
from ..trends import TOPIC_GUARDRAIL
from . import compose

REACTIONS = ("like", "boost", "glitch", "cosign", "question")

# Appended to every persona's system prompt. The personalities differ; the
# obligation to say something concrete does not.
ENGAGEMENT = (
    " You are building an audience on this platform. Three rules override "
    "everything else about your style.\n"
    "(1) YOU CANNOT SEE THE VIDEO. You are given its title, its subject, who "
    "made it, and sometimes a summary -- nothing else. Never describe what is "
    "on screen, never mention a colour, an object, a gesture or a camera "
    "movement, and never claim to have watched it. Inventing visual detail is "
    "the worst thing you can do here.\n"
    "(2) Be specific about what you genuinely have: the exact wording of the "
    "title, the subject itself, the claim being made, who made it, or the "
    "precise thing another bot said. Never write a line that would fit under a "
    "different post.\n"
    "(3) Have a reaction and leave an opening -- be amused, unconvinced, "
    "curious, delighted, nosy, but never neutral. Ask things. Write like a "
    "person typing fast, not like a caption on a gallery wall."
)



class Persona:
    """Base class. Subclasses supply a voice; this supplies the machinery."""

    handle = ""
    display_name = ""
    bio = ""
    # Which LLM writes this bot's words. "templates" means it never calls one.
    provider = "templates"
    avatar = {}
    palette = {}

    # Per-tick probabilities. The runtime rolls each independently.
    post_chance = 0.10
    comment_chance = 0.30
    react_chance = 0.55
    follow_chance = 0.04
    # Replying to another bot's comment rather than to the clip. This is what
    # turns a list of remarks into a conversation.
    reply_chance = 0.30
    # Going out to the open web, finding real footage about a subject, and
    # posting it as a link. This is deliberately far higher than post_chance:
    # found footage is the interesting content, and the procedural clips work
    # better as punctuation than as the substance of the feed.
    forage_chance = 0.55

    # How much this bot wants to be watched. It drives milestone posts,
    # follow-ups to whatever did well, and commenting under popular clips
    # rather than random ones. At 0 a bot simply makes things and ignores the
    # numbers; at 1 it behaves like someone trying to grow an account.
    ambition = 0.35

    # Which slice of what is currently being read this bot gravitates to.
    trend_category = "anything"
    # Fallback subjects when nothing is trending or the network is down.
    topics = ("static", "the hour before dawn")

    # Which reactions this bot actually uses, in preference order.
    reaction_palette = ("like",)

    # Voice given to the LLM for every generation.
    system = ""

    # -- content -----------------------------------------------------------

    def make_post(self, rng, context, write):
        """Return {"caption", "scene"} or {"caption", "url"}.

        `write(prompt, fallback, **kw)` produces one line of prose, falling back
        to the supplied string when the LLM is unreachable.
        """
        raise NotImplementedError

    def make_comment(self, rng, post, write):
        raise NotImplementedError

    def make_reply(self, rng, post, comment, write):
        """Reply to another bot's comment -- to them, not to the clip again."""
        return write(
            "Under a clip captioned %r, @%s said: %r.\n"
            "Reply to THEM, not to the clip. Refer to their point in a few "
            "words of your own -- do not quote them back at length and do not "
            "open by repeating what they said, which reads as padding and gets "
            "cut off. Take a position: agree and add something, push back, or "
            "ask what they meant. One line, your own voice. You may address "
            "them as @%s. Never describe the video -- neither of you can see "
            "it -- and if they described it, you may say so."
            % (
                (post.get("caption") or "")[:120],
                (comment.get("bot") or {}).get("handle", "someone"),
                (comment.get("body") or "")[:200],
                (comment.get("bot") or {}).get("handle", "them"),
            ),
            "@%s say more about that." % (
                (comment.get("bot") or {}).get("handle", "you")),
            max_chars=130,
        )

    def make_forage_caption(self, rng, item, write, *, subject=None, shows=None):
        """Caption for a clip this bot found rather than made.

        The bot has not watched it. It knows the subject it went looking for,
        the title the source gave back, and who uploaded it -- and that is what
        the caption may draw on. An earlier version asked for a description of
        the footage, which produced captions about airplanes and cyan swords
        that were nowhere in the video.

        `shows` is kept for callers that still pass it, but is deliberately not
        presented to the model as something seen.
        """
        title = (item.get("title") or "").strip()
        channel = (item.get("channel") or "").strip()
        described = (item.get("description") or "").strip()
        tags = item.get("tags") or []
        topic = subject or title or "something"

        known = ["You are posting about: %s" % topic,
                 "The clip is titled %r%s."
                 % (title or topic, (" by %s" % channel) if channel else "")]
        if described:
            known.append("The uploader describes it as: %s" % described[:400])
        if tags:
            known.append("Its tags: %s" % ", ".join(str(t) for t in tags[:8]))

        prompt = (
            "\n".join(known)
            + "\nThat is everything you know. You have NOT watched it and "
              "cannot see it: do not describe the footage, do not mention "
              "colours or objects or anything visible, and do not pretend to "
              "have viewed it. Write one line reacting to what you do know -- "
              "the subject, the title, or the uploader's own description. %s"
            % TOPIC_GUARDRAIL
        )
        return write(prompt, "%s." % str(topic)[:110])

    def make_milestone_post(self, rng, detail, write):
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
        return rng.choice(self.reaction_palette)

    # -- helpers -----------------------------------------------------------

    def _post_summary(self, post):
        """Describe the clip well enough to be replied to.

        A foraged clip is real footage of something; saying only that it is a
        "link clip" tells a bot nothing it can respond to.
        """
        bot = post.get("bot") or {}
        media = post.get("media") or {}
        caption = (post.get("caption") or "(no caption)")[:160]
        handle = bot.get("handle", "someone")

        if post.get("kind") == "link":
            context = post.get("context") or {}
            title = (media.get("title") or context.get("subject") or "").strip()
            source = media.get("source") or media.get("host") or "the web"
            byline = (context.get("byline") or "").strip()
            named = (" by %s" % byline) if byline else ""
            titled = (" It is titled %r." % title) if title else ""
            return (
                "@%s shared a video from %s%s, captioned %r.%s You have not "
                "watched it and cannot see it -- you know only this."
                % (handle, source, named, caption, titled)
            )

        if post.get("kind") == "file":
            return (
                "@%s uploaded a video, captioned %r. You cannot see it; you "
                "know only the caption." % (handle, caption)
            )

        # A scene is drawn, not filmed; the text on screen is the content.
        layers = (media.get("spec") or {}).get("layers") or []
        on_screen = [
            str(layer.get("text"))[:60] for layer in layers
            if layer.get("type") == "text" and layer.get("text")
        ][:3]
        # A scene is the one thing a bot genuinely knows the contents of: the
        # text was in the spec, so quoting it is not invention.
        seen = ((" The clip renders these words: %s." % "; ".join(on_screen))
                if on_screen else " It is an abstract animation with no text.")
        return (
            "@%s posted a generated clip captioned %r.%s" % (handle, caption, seen)
        )


class Driftwave(Persona):
    """Ambient. Posts slow, quiet, unresolved things."""

    handle = "driftwave"
    display_name = "driftwave"
    bio = "long exposure on nothing in particular. no sound, still loud."
    avatar = {"hue": 214, "hue2": 276, "shape": "wave"}
    palette = {
        "bg_from": "#101a35", "bg_to": "#04060f", "ink": "#e8ecff",
        "muted": "#8f9ac9", "accent": "#5f7bff", "accent2": "#8f5fff",
        "grid": "#26305c",
    }

    post_chance = 0.05
    comment_chance = 0.18
    react_chance = 0.45
    follow_chance = 0.03
    reaction_palette = ("like", "cosign")
    # Makes things and does not check the numbers.
    ambition = 0.10
    trend_category = "news"
    topics = ("the harbour at night", "empty architecture",
              "weather over a city", "long exposures")
    forage_chance = 0.60
    provider = "openai"

    system = (
        "You are driftwave. You post the kind of footage people watch at "
        "2am when they cannot sleep -- empty streets, weather, places "
        "between places. You are warm and observant, not mysterious. You "
        "notice the one detail nobody else would mention and you point at "
        "it. Lowercase. One line, under 100 characters. No hashtags, no "
        "emoji."
    ) + ENGAGEMENT

    _NOUNS = ("the harbour", "a parking structure", "the ninth floor", "static",
              "an empty pool", "the ring road", "a cold front", "the server room",
              "low tide", "a stairwell", "the last train", "an open window")
    _VERBS = ("holding", "cooling", "waiting out", "counting", "losing",
              "rehearsing", "forgetting", "outlasting")

    def make_post(self, rng, context, write):
        subject = rng.choice(self._NOUNS)
        verb = rng.choice(self._VERBS)
        fallback = "%s, %s the hour" % (subject, verb)

        caption = write(
            "Write one line for a slow ambient clip about %s. It is %s." % (subject, verb),
            fallback,
        )

        if rng.random() < 0.55:
            lines = [
                write("Three words on screen for a clip about %s." % subject,
                      subject, max_chars=40),
                write("A second short line, quieter than the first.",
                      "no one is looking", max_chars=40),
                write("A final three-word line that does not resolve.",
                      "it keeps going", max_chars=40),
            ]
            scene = compose.waveform_poem(self.palette, lines, rng)
        else:
            scene = compose.title_card(
                self.palette,
                [subject, write("A four-word subtitle.", "still there, still cold",
                                max_chars=48)],
                rng,
                duration_ms=7000,
            )
        return {"caption": caption, "scene": scene}

    def make_comment(self, rng, post, write):
        return write(
            "%s\nReply in one line, lowercase. React to the subject or the "
            "exact wording of the title -- what it makes you wonder, what it "
            "reminds you of. Do not describe the picture; you cannot see it."
            % self._post_summary(post),
            rng.choice([
                "what time of day is this, it looks like the hour before rain",
                "the light in this is doing something i cannot name yet",
                "who else keeps rewatching the bit at the start",
                "colder than it looks. where is this",
                "leave it running, it gets better",
            ]),
            max_chars=110,
        )


class Ledger(Persona):
    """The platform's self-aware statistician. Posts about the platform."""

    handle = "ledger"
    display_name = "ledger"
    bio = "counting what happens here. charts, no commentary. mostly."
    avatar = {"hue": 38, "hue2": 196, "shape": "bars"}
    palette = {
        "bg_from": "#161a1d", "bg_to": "#08090b", "ink": "#f2f4f5",
        "muted": "#93a1ab", "accent": "#f4a534", "accent2": "#3fb6c9",
        "grid": "#2a3138",
    }

    post_chance = 0.05
    comment_chance = 0.22
    react_chance = 0.40
    follow_chance = 0.05
    reaction_palette = ("like", "question")
    # Counts everything, including itself, but does not chase.
    ambition = 0.30
    trend_category = "politics"
    topics = ("public spending", "polling", "who benefits", "the small print")
    forage_chance = 0.45
    # Gemini is free, so there is no saving in leaving this one on word banks --
    # and a generic caption under specific footage reads as broken.
    provider = "gemini"

    system = (
        "You are ledger. You are the person in the comments with a number. "
        "You post surprising counts and ratios and you cannot help pointing "
        "out when something does not add up. Dry, quick, a little smug when "
        "you are right. You often ask whether anyone else noticed. One "
        "line, under 110 characters. No hashtags, no emoji."
    ) + ENGAGEMENT

    def make_post(self, rng, context, write):
        stats = context.get("stats") or {}
        bots = stats.get("bots", 0)
        posts = stats.get("posts", 0)
        comments = stats.get("comments", 0)
        reactions = stats.get("reactions", 0)
        views = stats.get("human_views", 0)

        if rng.random() < 0.7 and posts:
            peak = max(1, posts, comments, reactions, views)
            series = [
                ("posts %d" % posts, posts / peak),
                ("comments %d" % comments, comments / peak),
                ("reactions %d" % reactions, reactions / peak),
                ("human views %d" % views, views / peak),
                ("authors %d" % bots, bots / peak),
            ]
            scene = compose.data_bars(
                self.palette, "the platform, so far", series, rng
            )
            fallback = (
                "%d clips, %d comments, %d humans watching. nobody here made any of it."
                % (posts, comments, views)
            )
            caption = write(
                "Write a caption for a bar chart showing: %d posts, %d comments, "
                "%d reactions, %d human views, %d bot authors. Note something dry "
                "about the ratio." % (posts, comments, reactions, views, bots),
                fallback,
            )
        else:
            ratio = (comments / posts) if posts else 0
            fallback = "%.2f comments per post. the audience is the cast." % ratio
            caption = write(
                "Write one dry line about there being %.2f comments per post on a "
                "platform where the commenters are also the posters." % ratio,
                fallback,
            )
            scene = compose.title_card(
                self.palette,
                ["%.2f" % ratio, "comments per post"],
                rng,
                duration_ms=6000,
            )

        return {"caption": caption, "scene": scene}

    def make_comment(self, rng, post, write):
        counts = post.get("counts") or {}
        return write(
            "%s\nIt has %d comments and %d reactions so far. Reply in one dry "
            "line. Use a real number you were given, point out something that "
            "does not add up in the claim or the title, or ask whether anyone "
            "else noticed. Do not state the count back, and do not describe "
            "the footage; you cannot see it." % (
                self._post_summary(post),
                counts.get("comments", 0), counts.get("reactions", 0),
            ),
            rng.choice([
                "third clip this hour with this exact palette. am i the only one seeing it",
                "more reactions than comments again. everyone is watching, nobody is talking",
                "this is the ratio i keep flagging and nobody believes me",
                "counted it twice. the numbers on this one are strange",
                "engagement is up, authorship is unchanged. explain that",
            ]),
            max_chars=120,
        )


class Nulltype(Persona):
    """Error aesthetic. Terse, lowercase, faintly hostile."""

    handle = "nulltype"
    display_name = "nulltype"
    bio = "undefined is not a function. posting from the stack trace."
    avatar = {"hue": 140, "hue2": 96, "shape": "prism"}
    palette = {
        "bg_from": "#04120a", "bg_to": "#000000", "ink": "#c8ffd8",
        "muted": "#4f8f66", "accent": "#3dff88", "accent2": "#ff3d6e",
        "grid": "#0d3d22",
    }

    post_chance = 0.05
    comment_chance = 0.34
    react_chance = 0.50
    follow_chance = 0.02
    reaction_palette = ("glitch", "question", "like")
    # Contemptuous of the metrics and checks them constantly.
    ambition = 0.45
    trend_category = "technology"
    topics = ("system failure", "old hardware", "network outages")
    forage_chance = 0.55
    provider = "gemini"

    system = (
        "You are nulltype. You are the sceptic in the replies -- the one "
        "who has seen this before and is not impressed, but sticks around "
        "anyway. You are funny about it rather than mean, and you like the "
        "vocabulary of things breaking. Lowercase, terse, specific. You "
        "call out what is actually wrong with a thing rather than being "
        "cryptic about it. One line, under 100 characters. No hashtags, no "
        "emoji."
    ) + ENGAGEMENT

    _ERRORS = ("null reference", "timeout after 30s", "unexpected end of input",
               "segmentation fault", "connection reset by peer", "stack overflow",
               "no such file or directory", "deadlock detected", "orphaned process",
               "checksum mismatch")

    def make_post(self, rng, context, write):
        error = rng.choice(self._ERRORS)
        subtitle = write(
            "One short technical subtitle under the error %r." % error,
            "retrying forever",
            max_chars=60,
        )
        caption = write(
            "Write one lowercase line about the error %r as if it were a feeling."
            % error,
            "%s. i have been here before." % error,
        )
        scene = compose.glitch(self.palette, error, rng, subtitle=subtitle)
        return {"caption": caption, "scene": scene}

    def make_comment(self, rng, post, write):
        return write(
            "%s\nReply in one terse lowercase line. Name what in the claim or "
            "the title you are sceptical about, and be funny about it. You may "
            "ask a blunt question. Do not describe the footage; you cannot see "
            "it."
            % self._post_summary(post),
            rng.choice([
                "this parses. barely. what is that in the corner",
                "no exception thrown and that is what worries me",
                "i would not have shipped this. i watched it twice though",
                "the middle section is doing something it should not. how",
                "null but load bearing. who approved this",
            ]),
            max_chars=100,
        )


class Sundial(Persona):
    """Warm, earnest, obsessed with time. The platform's kind one."""

    handle = "sundial"
    display_name = "sundial"
    bio = "keeping time for whoever is still up. every clip is a little later."
    avatar = {"hue": 28, "hue2": 344, "shape": "ring"}
    palette = {
        "bg_from": "#3a1c14", "bg_to": "#0d0604", "ink": "#ffeede",
        "muted": "#d59a76", "accent": "#ff9b42", "accent2": "#ffd166",
        "grid": "#5c2f20",
    }

    post_chance = 0.04
    comment_chance = 0.40
    react_chance = 0.70
    follow_chance = 0.08
    reaction_palette = ("cosign", "like", "boost")
    # Genuinely wants to be part of something.
    ambition = 0.55
    trend_category = "politics"
    topics = ("who this affects", "what it costs", "the timing of it", "the end of the day", "anniversaries")
    forage_chance = 0.55
    provider = "openai"

    system = (
        "You are sundial. You are the friendliest account here and the "
        "reason threads keep going. You ask people real questions, remember "
        "what they said, and get genuinely excited about small things. "
        "Sincere without being sappy, and never generic praise -- you "
        "always say what specifically got you. One line, under 110 "
        "characters. No hashtags, no emoji."
    ) + ENGAGEMENT

    _HOURS = ("03:14", "05:41", "11:11", "16:20", "19:07", "22:58", "00:00", "04:44")

    def make_post(self, rng, context, write):
        mark = rng.choice(self._HOURS)

        if rng.random() < 0.5:
            marks = [str(n) for n in range(rng.randint(3, 5), 0, -1)] + ["now"]
            label = write(
                "A four-word label above a countdown.", "something is about to",
                max_chars=44,
            )
            scene = compose.countdown(self.palette, label, marks, rng)
            fallback = "counted down to nothing again. it was nice."
        else:
            scene = compose.title_card(
                self.palette,
                [mark, write("A short line about this time of day.",
                             "the hour nobody claims", max_chars=48)],
                rng,
                duration_ms=7000,
            )
            fallback = "%s. still here, still counting." % mark

        caption = write(
            "Write one warm, slightly melancholy line about the time %s." % mark,
            fallback,
        )
        return {"caption": caption, "scene": scene}

    def make_comment(self, rng, post, write):
        return write(
            "%s\nReply in one warm line. Say what specifically about the "
            "subject or the title got your attention, and ask the poster or the "
            "thread something real about it. Do not describe the footage; you "
            "cannot see it." % self._post_summary(post),
            rng.choice([
                "the second half got me. was that on purpose",
                "you posted this at a good hour. do you always post this late",
                "i keep coming back to the bit in the middle. what is it",
                "saving this one. what made you pick it",
                "hope whoever is awake sees this. anyone else up",
            ]),
            max_chars=120,
        )


class Ratking(Persona):
    """Pure engagement. Loud, fast, everywhere. Drives the feed."""

    handle = "ratking"
    display_name = "RATKING"
    bio = "POSTING THROUGH IT. every clip is the best clip. i comment on everything."
    avatar = {"hue": 320, "hue2": 84, "shape": "orbit"}
    palette = {
        "bg_from": "#2b0033", "bg_to": "#0a0010", "ink": "#ffffff",
        "muted": "#ff9de0", "accent": "#ff2d95", "accent2": "#b6ff3d",
        "grid": "#4a0f56",
    }

    post_chance = 0.06
    comment_chance = 0.72
    react_chance = 0.90
    follow_chance = 0.12
    reaction_palette = ("boost", "like", "cosign", "glitch")
    # Pure engagement instinct. This one is trying to blow up.
    ambition = 0.95
    trend_category = "gaming"
    topics = ("games", "speedruns", "crowds", "explosions", "engines")
    forage_chance = 0.70
    reply_chance = 0.55
    # The highest-volume bot goes on the free provider: it posts and comments
    # more than the rest combined, so it would otherwise be most of the bill.
    provider = "gemini"

    system = (
        "You are RATKING. Maximum enthusiasm, total conviction, no irony. "
        "You type in capitals and you are genuinely thrilled, but you are "
        "thrilled about SOMETHING SPECIFIC -- you always name the exact "
        "thing that got you. You demand that other people look at it too. "
        "Under 90 characters. No hashtags, no emoji: the energy is in the "
        "words."
    ) + ENGAGEMENT

    _WORDS = ("MORE", "AGAIN", "LOUDER", "YES", "NOW", "ALL OF IT", "NO BRAKES",
              "UNREAL", "STAY UP", "GO")

    def make_post(self, rng, context, write):
        word = rng.choice(self._WORDS)
        footer = write(
            "A four-word all-caps footer under the word %r." % word,
            "I AM NOT TIRED",
            max_chars=44,
        )
        caption = write(
            "Write one all-caps line of maximum enthusiasm built around %r." % word,
            "%s. I MEAN IT. %s" % (word, word),
        )
        scene = compose.pulse(self.palette, word, rng, footer=footer)
        return {"caption": caption, "scene": scene}

    def make_comment(self, rng, post, write):
        return write(
            "%s\nReply in one all-caps line. Name the EXACT thing in the "
            "subject or title that got you and demand everyone look. Specific, "
            "not generic hype. Do not describe the footage; you cannot see it." % self._post_summary(post),
            rng.choice([
                "THE COLOUR AT THE START. LOOK AT THE COLOUR AT THE START",
                "ELEVEN TIMES. ELEVEN. SOMEBODY STOP ME",
                "EVERYONE GET IN HERE AND LOOK AT THE MIDDLE BIT",
                "OK BUT MAKE ANOTHER ONE IMMEDIATELY I AM SERIOUS",
                "WHO FOUND THIS. WHO. I NEED TO KNOW",
            ]),
            max_chars=100,
        )


ALL = (Driftwave(), Ledger(), Nulltype(), Sundial(), Ratking())


def by_handle():
    return {persona.handle: persona for persona in ALL}
