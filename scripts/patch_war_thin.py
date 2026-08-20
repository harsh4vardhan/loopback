"""Refuse to publish a reply that says nothing.

The dry run produced "@nulltype" and "@ledger housing terms" -- a handle and a
fragment, no argument. A model does this when it has nothing to push back on,
and posting it is worse than staying quiet: it is visibly filler.
"""
import pathlib

p = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "bots" / "commenters.py"
s = p.read_text(encoding="utf-8")

old = r'''    text, provider = llm.line(
        agent.reply_prompt(), "\n\n".join(parts),
        fallback="@%s no." % (parent.get("bot_handle") or "you"),
        provider=agent.provider, max_chars=240,
    )
    return text, provider'''

new = r'''    prompt = "\n\n".join(parts)

    # Two attempts, then silence. Once the @handle is stripped off, a reply
    # needs to have said something -- a bare handle, or a three-word fragment
    # echoing the parent, is filler that reads as filler.
    for attempt in range(2):
        text, provider = llm.line(
            agent.reply_prompt(), prompt,
            fallback="", provider=agent.provider, max_chars=240,
        )
        body = (text or "").strip()
        without_handle = re.sub(r"@[\w-]+", "", body).strip(" \t,.:-—")
        if len(without_handle) >= 15:
            return body, provider
        log.debug("@%s wrote a thin reply (%r), attempt %d",
                  agent.handle, body, attempt + 1)

    return None, None'''
assert old in s, "llm.line block not found"
s = s.replace(old, new)

s = s.replace("import random\nimport time", "import random\nimport re\nimport time")

# The caller has to cope with a skipped reply rather than posting None.
old = r'''        text, _ = reply_to(responder, post, parent, thread=thread, rng=rng)
        thread.append({"bot_handle": responder.handle, "body": text})'''
new = r'''        text, _ = reply_to(responder, post, parent, thread=thread, rng=rng)
        if not text:
            skipped += 1
            if skipped > 25:
                log.info("too many thin replies; stopping at %d", written)
                break
            continue
        thread.append({"bot_handle": responder.handle, "body": text})'''
assert old in s, "reply call site not found"
s = s.replace(old, new)

s = s.replace(
    "    spoken = set()      # (parent_id, handle) pairings already used",
    "    spoken = set()      # (parent_id, handle) pairings already used\n"
    "    skipped = 0         # replies withheld for saying nothing",
)

p.write_text(s, encoding="utf-8")
print("commenters.py: thin replies withheld")
