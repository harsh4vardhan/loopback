"""Normalising the `link` post kind.

A bot can attach a URL instead of authoring pixels. This module decides how the
feed should present it: an inline <video> for a direct media file, a provider
iframe for the handful of hosts worth special-casing, or a link card otherwise.

Only http/https is accepted, and only a host that resolves publicly -- the feed
renders these in a viewer browser, so a bot must not be able to point it at
an internal address.
"""
import ipaddress
import re
import urllib.parse

DIRECT_EXTENSIONS = (".mp4", ".webm", ".m4v", ".mov", ".m3u8")

_YOUTUBE_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")
_VIMEO_HOSTS = ("vimeo.com", "www.vimeo.com", "player.vimeo.com")

_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_VIMEO_ID = re.compile(r"^\d{6,12}$")


class LinkError(ValueError):
    """The URL is unusable or not safe to embed."""


def _reject_private(host):
    """Block literal IPs in private ranges and obvious loopback names."""
    lowered = host.lower()
    if lowered in ("localhost", "localhost.localdomain") or lowered.endswith(".local"):
        raise LinkError("refusing to embed a local address")
    if lowered.endswith(".internal") or lowered == "metadata.google.internal":
        raise LinkError("refusing to embed an internal address")
    try:
        address = ipaddress.ip_address(lowered.strip("[]"))
    except ValueError:
        return  # a hostname, not a literal IP
    if (address.is_private or address.is_loopback or address.is_link_local
            or address.is_reserved or address.is_multicast):
        raise LinkError("refusing to embed a private or reserved IP")


def _youtube_id(parsed):
    if parsed.hostname in ("youtu.be",):
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif parsed.path.startswith("/shorts/"):
        candidate = parsed.path.split("/shorts/", 1)[1].split("/")[0]
    elif parsed.path.startswith("/embed/"):
        candidate = parsed.path.split("/embed/", 1)[1].split("/")[0]
    else:
        candidate = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
    return candidate if _YOUTUBE_ID.match(candidate or "") else None


def _vimeo_id(parsed):
    for segment in parsed.path.split("/"):
        if _VIMEO_ID.match(segment):
            return segment
    return None


def normalise(raw_url, *, poster=None, title=None):
    """Return the media payload for a link post, or raise LinkError."""
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise LinkError("link posts need a 'url'")
    url = raw_url.strip()
    if len(url) > 2000:
        raise LinkError("url is too long")

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise LinkError("url must be http or https, got %r" % (parsed.scheme or "none"))
    if not parsed.hostname:
        raise LinkError("url has no host")
    _reject_private(parsed.hostname)

    host = parsed.hostname.lower()
    path_lower = parsed.path.lower()

    payload = {
        "url": url,
        "host": host,
        "title": (title or "").strip()[:200],
    }
    if poster:
        payload["poster"] = str(poster)[:2000]

    if host in _YOUTUBE_HOSTS:
        video_id = _youtube_id(parsed)
        if video_id:
            payload.update({
                "provider": "youtube",
                "render": "iframe",
                "embed_url": (
                    "https://www.youtube-nocookie.com/embed/%s"
                    "?playsinline=1&rel=0&modestbranding=1" % video_id
                ),
                "poster": payload.get("poster")
                or "https://i.ytimg.com/vi/%s/hqdefault.jpg" % video_id,
            })
            return payload

    if host in _VIMEO_HOSTS:
        video_id = _vimeo_id(parsed)
        if video_id:
            payload.update({
                "provider": "vimeo",
                "render": "iframe",
                "embed_url": "https://player.vimeo.com/video/%s?dnt=1" % video_id,
            })
            return payload

    if path_lower.endswith(DIRECT_EXTENSIONS):
        payload.update({"provider": "direct", "render": "video"})
        return payload

    payload.update({"provider": "web", "render": "card"})
    return payload
