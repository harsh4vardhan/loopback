"""Blob storage for the `file` post kind.

Bytes go on disk, metadata goes in Postgres. On Railway, point MEDIA_DIR at a
mounted volume; without one, uploads live only until the next deploy.

Files are addressed by content hash, so two bots uploading the same clip cost
one copy on disk.
"""
import hashlib
import logging
import os
import pathlib
import threading

from . import config

log = logging.getLogger("loopback.storage")

# Video only. This is a video platform -- a still image is not a post here,
# so the only accepted uploads are formats a browser plays inline in a loop.
ALLOWED_TYPES = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}

_init_lock = threading.Lock()
_initialised = False


class StorageError(Exception):
    status = 400


def root():
    return pathlib.Path(config.MEDIA_DIR).expanduser()


def ensure_ready():
    """Create the media root, falling back to a temp dir if it is not writable."""
    global _initialised
    with _init_lock:
        if _initialised:
            return root()
        target = root()
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".writable"
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as exc:
            fallback = pathlib.Path("./var/media").resolve()
            log.warning(
                "MEDIA_DIR %s is not writable (%s); falling back to %s",
                target, exc, fallback,
            )
            fallback.mkdir(parents=True, exist_ok=True)
            config.MEDIA_DIR = str(fallback)
            target = fallback
        _initialised = True
        log.info("media root: %s", target)
        return target


def normalise_content_type(raw):
    value = (raw or "").split(";")[0].strip().lower()
    if value not in ALLOWED_TYPES:
        raise StorageError(
            "content type %r is not accepted; allowed: %s"
            % (raw, ", ".join(sorted(ALLOWED_TYPES)))
        )
    return value


def save(data, content_type):
    """Write bytes to the content-addressed store.

    Returns (relative_path, sha256_hex, byte_size).
    """
    if not data:
        raise StorageError("upload body was empty")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise StorageError(
            "upload is %d bytes; the limit is %d"
            % (len(data), config.MAX_UPLOAD_BYTES)
        )

    content_type = normalise_content_type(content_type)
    digest = hashlib.sha256(data).hexdigest()
    extension = ALLOWED_TYPES[content_type]
    relative = "%s/%s%s" % (digest[:2], digest, extension)

    base = ensure_ready()
    destination = base / relative
    destination.parent.mkdir(parents=True, exist_ok=True)

    if not destination.exists():
        # Write to a temp name then rename, so a crashed upload never leaves a
        # truncated file that later reads would trust.
        staging = destination.with_suffix(destination.suffix + ".part")
        with open(staging, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staging, destination)

    return relative, digest, len(data)


def resolve(relative_path):
    """Map a stored path back to an absolute path, refusing traversal."""
    base = ensure_ready().resolve()
    candidate = (base / str(relative_path)).resolve()
    if not str(candidate).startswith(str(base)):
        raise StorageError("refusing to serve a path outside the media root")
    if not candidate.is_file():
        raise StorageError("blob is not on disk")
    return candidate


def read(relative_path):
    return resolve(relative_path).read_bytes()


def usage():
    """Total bytes and file count under the media root, for /api/v1/stats."""
    base = ensure_ready()
    total = 0
    files = 0
    for path in base.rglob("*"):
        if path.is_file() and not path.name.endswith(".part"):
            total += path.stat().st_size
            files += 1
    return {"files": files, "bytes": total}
