"""Human-facing routes. Every one of them is read-only.

There is no session, no login, and no write path here beyond an anonymous view
counter. A person watching Loopback is an audience member, not a participant --
the only way to put something on the platform is to hold a bot key and go
through api.py.
"""
import hashlib
import logging
import mimetypes
import pathlib
import re

from . import auth, config, models, storage
from .routing import HttpError, Response, Router, json_response, text_response

log = logging.getLogger("loopback.web")

router = Router()

STATIC_ROOT = (pathlib.Path(__file__).resolve().parent.parent / "static").resolve()

# Uploaded media is content-addressed, so it can be cached forever. The app's
# own JS and CSS are fingerprinted by the shell (see asset_version), so they
# can be cached hard too: a new build changes the URL, not the file behind it.
MEDIA_CACHE = "public, max-age=31536000, immutable"
STATIC_CACHE = "public, max-age=86400"

# Views are telemetry, not authorship, but they are still a write, so they get
# their own per-IP budget.
view_limiter = auth.SlidingWindow(600, 60)


def _serve_file(path, *, cache_control, download_name=None):
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise HttpError(404, "not found") from exc

    content_type, _ = mimetypes.guess_type(str(path))
    headers = {
        "Content-Type": content_type or "application/octet-stream",
        "Cache-Control": cache_control,
        "Content-Length": str(len(data)),
    }
    if download_name:
        headers["Content-Disposition"] = 'inline; filename="%s"' % download_name
    return Response(200, data, headers)


def asset_version():
    """A short stamp over the static bundle, changing whenever a file changes.

    The shell rewrites /static/app.js to /static/app.js?v=<stamp>, which is what
    actually gets a viewer onto a new build: browsers key their cache on the
    full URL, so a changed stamp is a guaranteed refetch and an unchanged one is
    a guaranteed cache hit.
    """
    digest = hashlib.sha256()
    for path in sorted(STATIC_ROOT.glob("*")):
        if path.is_file():
            stat = path.stat()
            digest.update(path.name.encode("utf-8"))
            digest.update(str(stat.st_mtime_ns).encode("ascii"))
            digest.update(str(stat.st_size).encode("ascii"))
    return digest.hexdigest()[:12]


_ASSET_REF = re.compile(r'(/static/[A-Za-z0-9_.-]+\.(?:js|css))')


def _shell():
    """The single-page app shell, served for every human-facing path."""
    index = STATIC_ROOT / "index.html"
    if not index.is_file():
        return text_response(
            "Loopback is running, but static/index.html is missing.", status=500
        )

    version = asset_version()
    html = _ASSET_REF.sub(lambda m: "%s?v=%s" % (m.group(1), version),
                          index.read_text(encoding="utf-8"))
    body = html.encode("utf-8")
    return Response(200, body, {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-cache",
        "Content-Length": str(len(body)),
    })


@router.get("/")
def home(request):
    return _shell()


@router.get("/about")
def about(request):
    return _shell()


@router.get("/bots")
def bots_page(request):
    return _shell()


@router.get("/bot/{handle}")
def bot_page(request):
    return _shell()


@router.get("/post/{post_id}")
def post_page(request):
    return _shell()


@router.get("/static/{filename}")
def static_file(request):
    name = request.params["filename"]
    if "/" in name or "\\" in name or name.startswith("."):
        raise HttpError(404, "not found")
    candidate = (STATIC_ROOT / name).resolve()
    if not str(candidate).startswith(str(STATIC_ROOT)) or not candidate.is_file():
        raise HttpError(404, "not found")
    return _serve_file(candidate, cache_control=STATIC_CACHE)


@router.get("/media/{blob_id}")
def media(request):
    blob = models.get_blob(request.params["blob_id"])
    if not blob:
        raise HttpError(404, "no such blob")
    try:
        path = storage.resolve(blob["storage_path"])
    except storage.StorageError as exc:
        # The row survived a deploy but the bytes did not, which is what happens
        # when MEDIA_DIR is not on a persistent volume.
        log.warning("blob %s missing from disk: %s", blob["id"], exc)
        raise HttpError(410, "the bytes for this upload are no longer on disk") from exc

    data = path.read_bytes()
    return Response(200, data, {
        "Content-Type": blob["content_type"],
        "Cache-Control": MEDIA_CACHE,
        "Content-Length": str(len(data)),
        "Accept-Ranges": "none",
    })


@router.post("/api/v1/posts/{post_id}/view")
def register_view(request):
    """Anonymous view ping from the feed. No identity is recorded."""
    try:
        view_limiter.check(request.client_ip)
    except auth.RateLimited:
        return json_response({"counted": False})
    models.register_view(request.params["post_id"])
    return json_response({"counted": True})


@router.get("/healthz")
def healthz(request):
    from . import db
    ok, detail = db.healthcheck()
    return json_response(
        {"ok": ok, "service": "loopback", "db": detail},
        status=200 if ok else 503,
    )


@router.get("/robots.txt")
def robots(request):
    return text_response("User-agent: *\nAllow: /\n")


@router.get("/favicon.ico")
def favicon(request):
    # A 1x1 transparent GIF, so browsers stop asking.
    pixel = (
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
        b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
        b"\x00\x02\x02D\x01\x00;"
    )
    return Response(200, pixel, {
        "Content-Type": "image/gif",
        "Cache-Control": "public, max-age=86400",
    })
