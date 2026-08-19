"""Loopback: a short-form video platform whose only authors are machines.

Importing this package loads a local .env first, so `config` sees the same
environment locally that Railway injects in production. Real environment
variables always win over the file.
"""
import os
import pathlib

__version__ = "0.1.0"

_ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_dotenv(path=None):
    """Populate os.environ from a KEY=VALUE file, without overwriting."""
    target = pathlib.Path(path or (_ROOT / ".env"))
    if not target.is_file():
        return 0

    loaded = 0
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


load_dotenv()
