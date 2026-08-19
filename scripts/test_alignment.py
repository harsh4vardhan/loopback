"""Does the caption describe the clip that was attached?

Runs the forage path directly for each persona and prints the subject, the
footage found, and the caption written, so drift between them is visible.
"""
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import discovery, llm  # noqa: E402
from loopback.bots import personas, runtime  # noqa: E402


def main():
    print("sources:", discovery.configured())
    print("providers:", [n for n in llm.PROVIDERS if llm.available(n)])
    print()

    for index, persona in enumerate(personas.ALL):
        rng = random.Random(1000 + index)
        subject, background = runtime._subject_and_background(persona, rng)
        if not subject:
            print("@%-11s no subject available" % persona.handle)
            continue

        item = discovery.pick(subject, rng=rng)
        if not item:
            print("@%-11s subject=%-28r no footage found" % (persona.handle, subject))
            continue

        used = set()
        write = runtime._writer(persona, used, {"text": background})
        caption = persona.make_forage_caption(rng, item, write, subject=subject)

        print("@%s" % persona.handle)
        print("   subject : %s" % subject)
        print("   footage : %s  [%s]" % (item["title"][:56], item["source"]))
        print("   caption : %s" % caption)
        print("   wrote by: %s" % ", ".join(sorted(used)))

        # Now have another bot comment on that post, and check it is on topic.
        other = personas.ALL[(index + 1) % len(personas.ALL)]
        fake_post = {
            "kind": "link", "caption": caption,
            "media": {"title": item["title"], "source": item["source"]},
            "bot": {"handle": persona.handle},
            "counts": {"comments": 0},
        }
        used2 = set()
        brief = {"text": runtime._post_background(fake_post)}
        write2 = runtime._writer(other, used2, brief)
        print("   @%s replies: %s" % (
            other.handle, other.make_comment(rng, fake_post, write2)))
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
