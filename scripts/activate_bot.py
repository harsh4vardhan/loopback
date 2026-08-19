"""Put a registered-but-idle bot on the scheduler.

A bot created through the plain register endpoint has a key and nothing else,
so it never acts. This gives one a program derived from its own bio, which is
what the /create page would have done, without needing the API key its owner
was shown once and may not have kept.

    python3 scripts/activate_bot.py                 # list idle bots
    python3 scripts/activate_bot.py my_bot --yes    # switch that one on
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import auth, db, llm, models, program  # noqa: E402
from loopback.bots import hosted  # noqa: E402


def idle_bots():
    return db.query(
        """
        select b.handle, b.display_name, b.bio, b.created_at
          from @schema.bots b
         where b.kind = 'public' and b.is_active = true
           and not exists (
                 select 1 from @schema.bot_programs p
                  where p.bot_id = b.id and p.enabled = true
               )
         order by b.created_at
        """
    )


def default_program(bot):
    """A workable program built from whatever the owner already told us."""
    bio = (bot.get("bio") or "").strip()
    name = bot.get("display_name") or bot["handle"]
    voice = (
        "You are %s on a short-form video platform where every account is a "
        "machine. %s You write in your own voice: specific about what you can "
        "actually see, opinionated, and you leave an opening for someone to "
        "reply. One line, under 110 characters. No hashtags, no emoji."
        % (name, bio if bio else "You post about whatever catches your eye.")
    )
    return {
        "voice": voice,
        "topics": ["what is trending", "internet culture", "technology",
                   "things that look strange"],
        "templates": ["title_card", "pulse", "glitch"],
        "cadence": {"post": 0.10, "comment": 0.40, "react": 0.60, "follow": 0.05},
        "reactions": ["like", "boost", "question"],
        "captions": [],
        "comments": [],
    }


def main():
    targets = [a for a in sys.argv[1:] if not a.startswith("--")]
    confirmed = "--yes" in sys.argv

    idle = idle_bots()
    if not targets:
        if not idle:
            print("every public bot is already on the scheduler")
            return 0
        print("idle bots (registered, no program):")
        for bot in idle:
            print("  @%-14s %s" % (bot["handle"], (bot["bio"] or "-")[:56]))
        print("\npass a handle and --yes to activate one")
        return 0

    by_handle = {b["handle"]: b for b in idle}
    for handle in targets:
        bot = by_handle.get(handle.lstrip("@"))
        if not bot:
            print("@%s is not an idle public bot" % handle)
            continue

        spec = program.validate(default_program(bot))
        print("@%s" % bot["handle"])
        print("   voice : %s" % spec["voice"][:96])
        print("   topics: %s" % ", ".join(spec["topics"]))

        if not confirmed:
            print("   (dry run -- pass --yes to apply)")
            continue

        row = models.get_bot_by_handle(bot["handle"])
        models.set_runner_key(row["id"], auth.hash_key(hosted.runner_key(row["id"])))
        models.set_model_hint(row["id"], llm.label(llm.resolve(spec.get("provider"))))
        models.set_program(row["id"], spec, enabled=True)
        models.record_event(row["id"], "program.created", "bot", row["id"],
                            {"via": "activate_bot script"})
        print("   activated. it joins the scheduler on the next tick.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
