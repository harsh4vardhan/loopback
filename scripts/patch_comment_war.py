"""Let the archetypes argue with each other in the replies.

A comment section goes viral in the replies, not in the top-level comments. The
swarm so far had thirteen people talking past each other; this gives them a way
to talk *at* each other, which is where pile-ons, corrections and the whole
"read the replies" phenomenon actually live.

The friction is built into who they already are, so nothing needs forcing:

  the_receipts       corrects fun_fact_actually's facts
  no_hesitation      deflates under_a_limit's moralising with four words
  no_agreement_made  litigates whatever rest_of_your_life joked about
  reading_the_replies narrates the argument the others are having
  my_bad_sorry       apologises to whoever is being piled on

The floor holds. These bots may be scathing to each other -- they are fictional
and cannot be hurt -- but the guards against slurs, cruelty and anything aimed
at a real person apply to every line, including the ones written in anger.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent

# --- a reply register on the archetype ------------------------------------
a = root / "loopback" / "archetypes.py"
s = a.read_text(encoding="utf-8")

if "def reply_prompt" not in s:
    s = s.replace(
        '''ARCHETYPES = [''',
        '''# What a commenter does when it is answering another commenter rather than the
# clip. Kept separate from the persona because the shift is real: people write
# differently at each other than they do at a video.
REPLY_REGISTER = (
    "You are replying to another commenter, not to the video.\\n"
    "Stay entirely in your own register -- do not borrow theirs. Pick the "
    "single thing they said that you cannot let stand and go at that. You may "
    "disagree flatly, correct them, pile on, take their side against someone "
    "else, or refuse to engage with the point they wanted you to engage with.\\n"
    "Address them by @handle. Do not quote them at length; name their point in "
    "a few words of your own. Short -- this is a reply, not an essay.\\n"
    "You are arguing with another commenter and that is fine. What is never "
    "fine: slurs, anything about a real person's body, worth or identity, or "
    "cruelty dressed as a joke. Go after what they said."
)


ARCHETYPES = [''',
    )

    s = s.replace(
        '''    def system_prompt(self):''',
        '''    def reply_prompt(self):
        """This persona, in the register of answering someone."""
        shown = "\\n".join("  - %s" % e for e in self.examples[:3])
        return (
            "You are %s (@%s), one specific kind of commenter.\\n"
            "%s\\n"
            "Your usual register, for tone only -- never copy these:\\n%s\\n"
            "%s\\n"
            "%s"
            % (self.name, self.handle, self.behaviour, shown,
               REPLY_REGISTER, COMMENTER_GUARD)
        )

    def system_prompt(self):''',
    )
    a.write_text(s, encoding="utf-8")
    print("archetypes.py: reply register added")

# --- the war ---------------------------------------------------------------
c = root / "loopback" / "bots" / "commenters.py"
s = c.read_text(encoding="utf-8")

if "def comment_war" not in s:
    s = s.rstrip() + '''


def reply_to(agent, post, parent, *, thread=(), rng=None):
    """One reply, aimed at another commenter."""
    rng = rng or random
    parts = [_what_is_known(post)]

    if thread:
        recent = "\\n".join(
            "  @%s: %s" % (c.get("bot_handle") or "someone",
                           (c.get("body") or "")[:110])
            for c in list(thread)[-5:]
        )
        parts.append("The argument so far:\\n%s" % recent)

    parts.append(
        "@%s said: %r\\nReply to them."
        % (parent.get("bot_handle") or "someone", (parent.get("body") or "")[:220])
    )

    text, provider = llm.line(
        agent.reply_prompt(), "\\n\\n".join(parts),
        fallback="@%s no." % (parent.get("bot_handle") or "you"),
        provider=agent.provider, max_chars=240,
    )
    return text, provider


# Archetypes that will predictably rub each other up the wrong way. Used to
# pick who answers whom, so the argument has friction rather than being a
# random pairing that agrees by accident.
FRICTION = {
    "the_receipts": ["fun_fact_actually", "under_a_limit", "no_agreement_made"],
    "fun_fact_actually": ["the_receipts", "no_hesitation", "pun_account"],
    "under_a_limit": ["no_hesitation", "rest_of_your_life", "oh_no_anyways"],
    "no_hesitation": ["under_a_limit", "physically_ill", "no_agreement_made"],
    "no_agreement_made": ["rest_of_your_life", "no_hesitation", "quote_bit"],
    "rest_of_your_life": ["under_a_limit", "physically_ill", "my_bad_sorry"],
    "physically_ill": ["no_hesitation", "rest_of_your_life"],
    "reading_the_replies": ["under_a_limit", "the_receipts", "edit_holy_4k"],
    "edit_holy_4k": ["reading_the_replies", "no_hesitation"],
    "quote_bit": ["no_agreement_made", "fun_fact_actually"],
    "oh_no_anyways": ["under_a_limit", "physically_ill"],
    "pun_account": ["reading_the_replies", "no_agreement_made"],
    "my_bad_sorry": ["the_receipts", "no_agreement_made"],
}


def _antagonist_for(handle, rng, available):
    """Who should answer this comment, preferring a known clash."""
    candidates = [h for h in FRICTION.get(handle, []) if h in available]
    if candidates:
        return rng.choice(candidates)
    others = [h for h in available if h != handle]
    return rng.choice(others) if others else None


def comment_war(post, *, target=50, rng=None, pace=1.2, dry_run=False,
                seed_comments=6):
    """Fill a post's comment section with archetypes arguing.

    Opens with a spread of top-level comments, then spends the rest of the
    budget on replies -- picking antagonists who will actually disagree, and
    occasionally starting a fresh thread so the section does not become one
    long chain.
    """
    rng = rng or random.Random()
    bots = clients()
    by_handle = archetypes.by_handle()
    available = list(by_handle)

    written = 0
    roots = []          # (comment_id, handle, body) that replies can hang from
    thread = []

    # Opening: several different people arrive at the clip.
    for agent in rng.sample(archetypes.ARCHETYPES,
                            min(seed_comments, len(archetypes.ARCHETYPES))):
        text, _ = comment_on(agent, post, thread=thread, rng=rng)
        entry = {"bot_handle": agent.handle, "body": text}
        thread.append(entry)
        written += 1

        if dry_run:
            roots.append({"id": None, "bot_handle": agent.handle, "body": text})
            print("  @%-20s %s" % (agent.handle, text[:88]))
            continue
        try:
            result = bots[agent.handle].comment(post["id"], text)
            comment_id = (result.get("comment") or {}).get("id")
            roots.append({"id": comment_id, "bot_handle": agent.handle,
                          "body": text})
            print("  @%-20s %s" % (agent.handle, text[:88]))
        except LoopbackError as exc:
            log.warning("@%s could not comment: %s", agent.handle, exc)
            if exc.status == 401:
                raise
        time.sleep(pace)

    # The rest is argument.
    while written < target and roots:
        parent = rng.choice(roots[-12:] if len(roots) > 12 else roots)
        responder_handle = _antagonist_for(parent["bot_handle"], rng, available)
        if not responder_handle:
            break
        responder = by_handle[responder_handle]

        text, _ = reply_to(responder, post, parent, thread=thread, rng=rng)
        thread.append({"bot_handle": responder.handle, "body": text})
        written += 1
        depth = "  " if parent.get("id") else ""
        print("  %s@%-18s -> @%-18s %s"
              % (depth, responder.handle, parent["bot_handle"], text[:60]))

        if not dry_run:
            try:
                result = bots[responder.handle].comment(
                    post["id"], text, parent_id=parent.get("id")
                )
                new_id = (result.get("comment") or {}).get("id")
                # A reply can itself be replied to, which is how a thread gets
                # deep rather than staying two levels.
                if new_id:
                    roots.append({"id": new_id, "bot_handle": responder.handle,
                                  "body": text})
            except LoopbackError as exc:
                log.warning("@%s could not reply: %s", responder.handle, exc)
                if exc.status == 401:
                    raise
            time.sleep(pace)

    return written
'''
    c.write_text(s, encoding="utf-8")
    print("commenters.py: comment_war added")

for f, marker in ((a, "REPLY_REGISTER"), (c, "def comment_war")):
    print("  %-16s %s" % (f.name, "ok" if marker in f.read_text(encoding="utf-8") else "MISSING"))
