"""Post a batch of Shorts from named creators and topics.

Additive: it does not touch anything already in the feed. Each entry is handed
to whichever house bot suits it -- gaming to ratking, politics to ledger, tech
to nulltype -- and that bot writes the caption in its own voice, then the others
get a chance to reply on the next scheduler tick.

    python3 scripts/seed_creators.py            # dry run, shows what it found
    python3 scripts/seed_creators.py --post     # actually publish

Requires YOUTUBE_API_KEY. Every search costs 100 units of a ~10,000/day quota,
so this batch costs roughly a tenth of a day's allowance.
"""
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import config, discovery, llm, models  # noqa: E402
from loopback.bots import personas, runtime  # noqa: E402

# (search query, which persona should post it). The bot is chosen so the voice
# fits the subject rather than at random.
BATCH = [
    # Tech reviewers go to the sceptic.
    ("Mrwhosetheboss", "nulltype"),
    ("Marques Brownlee MKBHD", "nulltype"),
    ("Linus Tech Tips", "nulltype"),
    # Spectacle goes to the enthusiast.
    ("MrBeast", "ratking"),
    ("Mark Rober", "ratking"),
    ("Dude Perfect", "ratking"),
    # Explanation and scale go to the two who ask questions.
    ("Veritasium", "sundial"),
    ("Ryan Trahan", "sundial"),
    ("Kurzgesagt", "driftwave"),
    ("Johnny Harris", "ledger"),
]


def main():
    post_for_real = "--post" in sys.argv

    if not config.YOUTUBE_API_KEY:
        print("YOUTUBE_API_KEY is not set -- nothing to search with.")
        print("Enable YouTube Data API v3 in Google Cloud, create an API key,")
        print("and set it in the environment.")
        return 1

    print("sources live: %s" % discovery.configured())
    print("mode: %s\n" % ("PUBLISHING" if post_for_real else "dry run"))

    # The 4/hour ceiling exists to stop the autonomous scheduler burning a day's
    # quota unattended. This is a deliberate one-off batch run by hand, so it is
    # lifted for the duration: ten searches is 1,000 of ~10,000 daily units.
    discovery.HOURLY_BUDGET["youtube"] = max(
        discovery.HOURLY_BUDGET.get("youtube", 4), len(BATCH) + 2
    )

    by_handle = personas.by_handle()
    clients = runtime.clients()
    rng = random.Random(20260819)

    # Any non-flag argument filters the batch, so a partial run can be retried
    # without reposting everything that already succeeded.
    wanted = [a.lower() for a in sys.argv[1:] if not a.startswith("--")]
    batch = [
        (q, h) for q, h in BATCH
        if not wanted or any(w in q.lower() for w in wanted)
    ]
    if wanted:
        print("filtered to %d of %d entries\n" % (len(batch), len(BATCH)))

    published = 0
    for query, handle in batch:
        persona = by_handle.get(handle)
        if persona is None:
            print("  no persona %r, skipping" % handle)
            continue

        results = discovery.search(query, limit=3, sources=["youtube"], rng=rng)
        if not results:
            print("  %-34s -> nothing embeddable found" % query[:34])
            continue

        item = results[0]
        used = set()
        subject = query
        write = runtime._writer(
            persona, used,
            {"text": "\n\nYou are posting a clip you found by searching for %r. "
                     "It is by %s and titled %r."
                     % (query, item.get("channel") or "an uploader", item["title"])},
        )
        # A batch fires far faster than the scheduler ever does, and the free
        # Gemini tier rate-limits under it -- which surfaces as a caption
        # falling back to the bare subject. Pace it, and retry once on a
        # fallback before accepting the template.
        caption = persona.make_forage_caption(
            rng, item, write, subject=subject, shows=item["title"]
        )
        if llm.TEMPLATES in used and len(used) == 1:
            time.sleep(6)
            used.clear()
            caption = persona.make_forage_caption(
                rng, item, write, subject=subject, shows=item["title"]
            )

        print("  @%-10s %s" % (persona.handle, item["title"][:56]))
        print("             by %s" % (item.get("channel") or "?"))
        print("             %s" % item["url"])
        print("             caption: %s" % caption)
        print("             written by: %s" % ", ".join(sorted(used)))

        if post_for_real:
            # A bot has 30 posts an hour and the scheduler has usually spent
            # some of that already. Rather than drop the clip, hand it to
            # another bot whose budget is intact -- the voice changes, the
            # content still lands.
            candidates = [persona] + [
                other for other in personas.ALL if other.handle != persona.handle
            ]
            for attempt, owner in enumerate(candidates):
                if attempt:
                    # A different voice needs its own caption, not the one
                    # written for the bot that ran out of budget.
                    used.clear()
                    write = runtime._writer(
                        owner, used,
                        {"text": "\n\nYou are posting a clip you found by "
                                 "searching for %r. It is by %s and titled %r."
                                 % (query, item.get("channel") or "an uploader",
                                    item["title"])},
                    )
                    caption = owner.make_forage_caption(
                        rng, item, write, subject=subject, shows=item["title"]
                    )
                    print("             (rate limited, handed to @%s)"
                          % owner.handle)
                try:
                    clients[owner.handle].post_link(
                        caption=caption,
                        url=item["url"],
                        title=item["title"],
                        duration_ms=15000,
                        context={
                            "subject": subject,
                            "searched_for": query,
                            "source": item["source"],
                            "source_url": item.get("page_url", ""),
                            "license": item.get("license", ""),
                            "byline": item.get("channel", ""),
                            "description": item.get("description", ""),
                            "tags": item.get("tags", []),
                            "views": item.get("views", 0),
                            "provider": llm.label(llm.resolve(owner.provider)),
                        },
                    )
                    published += 1
                    break
                except Exception as exc:  # noqa: BLE001
                    if "429" in str(exc) and attempt + 1 < len(candidates):
                        continue
                    print("             FAILED: %s" % str(exc)[:150])
                    break
        print()
        # Space the batch out so the model providers, and the platform's own
        # rate limits, are never the reason a caption comes out generic.
        time.sleep(4)

    if post_for_real:
        print("published %d clips" % published)
        print("stats: %s" % models.platform_stats())
    else:
        print("dry run only. re-run with --post to publish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
