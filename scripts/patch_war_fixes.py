"""Three fixes the dry run exposed.

A bot addressed itself, @fun_fact_actually answered the same comment twice with
the same fact about sword durability, and the dry run could not see the existing
comments it claimed to be previewing an argument with.
"""
import pathlib

p = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "bots" / "commenters.py"
s = p.read_text(encoding="utf-8")

# 1. Name the target explicitly. Asked to infer who it is answering from a
# transcript that ends with its own line, a bot will address itself.
old = r'''    parts.append(
        "@%s said: %r\nReply to them."
        % (parent.get("bot_handle") or "someone", (parent.get("body") or "")[:220])
    )'''
new = r'''    target = parent.get("bot_handle") or "someone"
    parts.append(
        "You are replying to @%s, and to nobody else. They said:\n  %s\n"
        "Open by addressing @%s. Never address yourself (@%s) -- you are not "
        "one of the voices in the transcript above, you are the one answering it."
        % (target, (parent.get("body") or "")[:220], target, agent.handle)
    )'''
assert old in s, "reply prompt block not found"
s = s.replace(old, new)

# 2. No pairing twice. Two fun facts about diamond sword durability under one
# comment is the clearest tell that a section was filled by a machine.
old = r'''        pool = roots[-14:] if len(roots) > 14 else roots
        if len(roots) > 14 and rng.random() < 0.25:
            pool = roots        # occasionally revive an older thread
        parent = rng.choice(pool)
        responder_handle = _antagonist_for(parent["bot_handle"], rng, available)
        if not responder_handle:
            break
        responder = by_handle[responder_handle]'''
new = r'''        pool = roots[-14:] if len(roots) > 14 else roots
        if len(roots) > 14 and rng.random() < 0.25:
            pool = roots        # occasionally revive an older thread

        # Look for a pairing that has not happened yet, rather than taking the
        # first one offered and repeating material.
        parent = responder_handle = None
        for _ in range(24):
            candidate = rng.choice(pool)
            who = _antagonist_for(candidate["bot_handle"], rng, available)
            if who and (candidate.get("id"), who) not in spoken:
                parent, responder_handle = candidate, who
                break
        if not responder_handle:
            log.info("pairings exhausted on this post; stopping at %d", written)
            break
        spoken.add((parent.get("id"), responder_handle))
        responder = by_handle[responder_handle]'''
assert old in s, "parent selection block not found"
s = s.replace(old, new)

old = r'''    written = 0
    roots = []          # comments a reply can hang from
    thread = []'''
new = r'''    written = 0
    roots = []          # comments a reply can hang from
    thread = []
    spoken = set()      # (parent_id, handle) pairings already used'''
assert old in s, "state block not found"
s = s.replace(old, new)

# 3. A dry run blind to the existing section is not a preview of anything. The
# post id is real either way; only the writes are withheld.
old = r'''    if not dry_run:
        for existing in models.list_comments(post["id"], limit=200):
            roots.append({
                "id": existing.get("id"),
                "bot_handle": existing.get("bot_handle"),
                "body": existing.get("body"),
            })
            thread.append({
                "bot_handle": existing.get("bot_handle"),
                "body": existing.get("body"),
            })
        if roots:
            print("  (%d existing comments to argue with)" % len(roots))'''
new = r'''    for existing in models.list_comments(post["id"], limit=200):
        roots.append({
            "id": existing.get("id"),
            "bot_handle": existing.get("bot_handle"),
            "body": existing.get("body"),
        })
        thread.append({
            "bot_handle": existing.get("bot_handle"),
            "body": existing.get("body"),
        })
    if roots:
        print("  (%d existing comments to argue with)" % len(roots))'''
assert old in s, "seeding block not found"
s = s.replace(old, new)

p.write_text(s, encoding="utf-8")
print("commenters.py: three fixes applied")
