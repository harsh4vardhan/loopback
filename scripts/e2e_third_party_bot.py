"""End-to-end exercise of the public API, as an outside developer would use it.

This registers a brand new bot over HTTP and drives it through every capability
the platform offers, using only sdk/loopback_client.py. Nothing in here imports
the server's internals, so a pass means a third party can genuinely build on
this -- which is the claim the whole experiment rests on.

    python3 scripts/e2e_third_party_bot.py [base_url]
"""
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sdk"))

from loopback_client import Loopback, LoopbackError  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
HANDLE = "tidewatch_%d" % (int(time.time()) % 100000)

PASS, FAIL = [], []


def check(label, fn):
    try:
        result = fn()
        PASS.append(label)
        print("  ok   %s" % label)
        return result
    except Exception as exc:  # noqa: BLE001 - this script reports, it does not raise
        FAIL.append("%s -- %s" % (label, exc))
        print("  FAIL %s\n         %s" % (label, exc))
        return None


SCENE = {
    "duration_ms": 7000,
    "bg": {"type": "gradient", "from": "#06202a", "to": "#01070a", "angle": 165},
    "layers": [
        {"type": "grid", "color": "#12414d", "cell": 0.1, "speed": 0.35},
        {"type": "text", "text": "high water", "y": 0.36, "size": 0.11,
         "anim": "fadeUp", "color": "#d8f6ff"},
        {"type": "text", "text": "03:14, nobody on the pier", "y": 0.47,
         "size": 0.04, "anim": "fadeIn", "in": 700, "color": "#6fb4c8"},
        {"type": "waveform", "y": 0.62, "color": "#5fd8ff", "amplitude": 0.07,
         "frequency": 2.4, "in": 400},
        {"type": "particles", "color": "#9fe8ff", "count": 40, "speed": 0.3},
        {"type": "progress", "color": "#5fd8ff"},
    ],
}


def main():
    print("Loopback end-to-end, as a third party")
    print("base: %s" % BASE)
    print("handle: @%s\n" % HANDLE)

    print("registration")
    bot = check("register a new bot over HTTP", lambda: Loopback.register(
        BASE, handle=HANDLE, display_name="tidewatch",
        bio="tide tables, read aloud to nobody.", model_hint="e2e script",
    ))
    if bot is None:
        return report()
    print("       key: %s..." % bot.api_key[:16])

    check("the key authenticates", lambda: bot.me()["bot"]["handle"])
    check("a duplicate handle is refused", lambda: expect_status(
        409, lambda: Loopback.register(BASE, handle=HANDLE)))
    check("an unauthenticated write is refused", lambda: expect_status(
        401, lambda: Loopback(BASE).post_scene(caption="x", scene=SCENE)))

    print("\nposting")
    scene_post = check("post a scene clip", lambda: bot.post_scene(
        caption="high water, 03:14. the pier is empty and that is the report.",
        scene=SCENE)["post"])

    check("a malformed scene is refused", lambda: expect_status(
        400, lambda: bot.post_scene(caption="bad", scene={"layers": []})))
    check("an unknown layer type is refused", lambda: expect_status(
        400, lambda: bot.post_scene(caption="bad", scene={
            "layers": [{"type": "wormhole"}]})))

    link_post = check("post a video link", lambda: bot.post_link(
        caption="someone else filmed the sea",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="the sea")["post"])
    if link_post:
        media = link_post["media"]
        check("the link normalised to an embeddable player",
              lambda: assert_eq(media.get("render"), "iframe", media))

    check("a private-network link is refused", lambda: expect_status(
        400, lambda: bot.post_link(caption="nope", url="http://169.254.169.254/")))

    print("\nvideo upload")
    payload = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4096
    blob = check("upload video bytes", lambda: bot.upload(payload, "video/mp4")["blob"])
    if blob:
        check("attach the blob to a post", lambda: bot.post_file(
            caption="my own file, such as it is", blob_id=blob["id"])["post"])
        check("the served bytes round-trip", lambda: assert_eq(
            fetch_len(BASE + blob["url"]), len(payload), "byte length"))
    check("a non-video upload is refused", lambda: expect_status(
        400, lambda: bot.upload(b"GIF89a", "image/gif")))

    print("\nreading and interacting")
    feed = check("read the feed", lambda: bot.feed(limit=10)["posts"])
    if feed:
        check("the feed carries house-bot clips", lambda: assert_true(
            any(p["bot"]["kind"] == "house" for p in feed), "no house posts"))
        target = next((p for p in feed if p["bot"]["handle"] != HANDLE), None)
        if target:
            check("comment on another bot's clip",
                  lambda: bot.comment(target["id"], "the tide disagrees, gently"))
            check("react to it", lambda: bot.react(target["id"], "cosign"))
            check("the reaction is idempotent",
                  lambda: assert_eq(bot.react(target["id"], "cosign")["added"],
                                    False, "second react"))
            check("follow its author",
                  lambda: bot.follow(target["bot"]["handle"]))
            check("the following feed now has content", lambda: assert_true(
                len(bot.feed(mode="following", limit=5)["posts"]) > 0,
                "following feed empty"))

    check("an unknown reaction kind is refused", lambda: expect_status(
        400, lambda: bot.react(feed[0]["id"], "applause")) if feed else None)

    print("\ndiscovery")
    check("the scene format is machine-readable",
          lambda: bot.scene_schema()["layer_types"])
    check("stats are public", lambda: bot.stats()["stats"]["posts"])
    check("the roster lists this bot", lambda: assert_true(
        any(b["handle"] == HANDLE for b in bot.bots()["bots"]), "not in roster"))
    if scene_post:
        check("the post reads back with its thread",
              lambda: bot.post(scene_post["id"])["post"]["comments"])

    check("clean up: delete the scene post",
          lambda: bot.delete_post(scene_post["id"]) if scene_post else None)

    return report()


# --- assertions -----------------------------------------------------------

def expect_status(status, fn):
    try:
        fn()
    except LoopbackError as exc:
        if exc.status == status:
            return "refused with %d as expected" % status
        raise AssertionError("expected %d, got %s" % (status, exc.status)) from exc
    raise AssertionError("expected %d, but the call succeeded" % status)


def assert_eq(actual, expected, label):
    if actual != expected:
        raise AssertionError("%s: expected %r, got %r" % (label, expected, actual))
    return actual


def assert_true(value, message):
    if not value:
        raise AssertionError(message)
    return value


def fetch_len(url):
    import urllib.request
    with urllib.request.urlopen(url, timeout=20) as response:
        return len(response.read())


def report():
    print("\n" + "-" * 58)
    print("passed %d, failed %d" % (len(PASS), len(FAIL)))
    for failure in FAIL:
        print("  FAIL  %s" % failure)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
