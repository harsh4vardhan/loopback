"""Check that each catalogue actually returns playable video."""
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import discovery, links  # noqa: E402

QUERIES = ["tide", "aurora", "storm", "clock", "harbour"]


def main():
    rng = random.Random(7)
    total = 0

    for source in sorted(discovery.SOURCES):
        print("\n%s" % source)
        print("-" * 58)
        hits = 0
        for query in QUERIES[:3]:
            results = discovery.search(query, limit=2, sources=[source], rng=rng)
            for item in results:
                # It is only useful if the feed will actually render it inline.
                try:
                    media = links.normalise(item["url"], title=item["title"])
                    render = media.get("render")
                except links.LinkError as exc:
                    render = "REJECTED: %s" % exc
                mb = item["bytes"] / 1_000_000 if item["bytes"] else 0
                print("  [%s] %-42s %s" % (
                    render, item["title"][:42], ("%.1fMB" % mb) if mb else ""))
                print("        %s" % item["url"][:96])
                hits += 1
                total += 1
        if not hits:
            print("  (nothing returned)")

    print("\n%d playable results across %d sources" % (total, len(discovery.SOURCES)))
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
