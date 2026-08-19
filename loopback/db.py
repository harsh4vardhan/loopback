"""Postgres access over Neon's SQL-over-HTTP endpoint.

Neon exposes every branch at https://<host>/sql, which accepts a parameterised
query as JSON and returns rows as JSON. That means a stdlib urllib request is a
complete Postgres client -- no driver, no build step, no wheels.

The endpoint is one round trip per call and autocommits, so multi-statement
atomicity goes through transaction() which uses the batch form.
"""
import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request

from . import config

log = logging.getLogger("loopback.db")

_endpoint_cache = {}
_lock = threading.Lock()


class DatabaseError(RuntimeError):
    """A query was rejected by Postgres, or the endpoint was unreachable."""

    def __init__(self, message, *, code=None, query=None):
        super().__init__(message)
        self.code = code
        self.query = query


def _endpoint(conn_string):
    """Derive https://<host>/sql from a postgres:// connection string."""
    with _lock:
        if conn_string in _endpoint_cache:
            return _endpoint_cache[conn_string]

    parsed = urllib.parse.urlparse(conn_string)
    if parsed.scheme not in ("postgres", "postgresql"):
        raise DatabaseError(
            "DATABASE_URL must be a postgres:// or postgresql:// URL, got "
            f"{parsed.scheme!r}"
        )
    host = parsed.hostname
    if not host:
        raise DatabaseError("DATABASE_URL has no host")
    if not host.endswith(".neon.tech"):
        raise DatabaseError(
            f"host {host!r} is not a Neon host; the HTTP transport only speaks "
            "to Neon. Point DATABASE_URL at a Neon branch."
        )
    url = f"https://{host}/sql"

    with _lock:
        _endpoint_cache[conn_string] = url
    return url


SCHEMA_SENTINEL = "@schema."


def qualify(sql):
    """Rewrite the @schema. sentinel to the configured Postgres schema."""
    return sql.replace(SCHEMA_SENTINEL, '"' + config.DB_SCHEMA + '".')


def _post(payload, *, headers=None, timeout=30):
    conn = config.DATABASE_URL
    if not conn:
        raise DatabaseError(
            "DATABASE_URL is not set. The server cannot reach Postgres."
        )

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(_endpoint(conn), data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Neon-Connection-String", conn)
    # Typed output: Neon decodes jsonb into objects and numerics into numbers,
    # so the model layer does not re-parse every column.
    req.add_header("Neon-Raw-Text-Output", "false")
    req.add_header("Neon-Array-Mode", "false")
    for key, value in (headers or {}).items():
        req.add_header(key, value)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
            message = parsed.get("message") or parsed.get("error") or raw
            code = parsed.get("code")
        except json.JSONDecodeError:
            message, code = raw, None
        raise DatabaseError(
            f"postgres error ({exc.code}): {message}",
            code=code,
            query=payload.get("query"),
        ) from exc
    except urllib.error.URLError as exc:
        raise DatabaseError(f"cannot reach Neon endpoint: {exc.reason}") from exc


def query(sql, params=None, *, timeout=30):
    """Run one statement; return a list of dict rows (empty for writes)."""
    result = _post({"query": qualify(sql), "params": list(params or [])}, timeout=timeout)
    return result.get("rows") or []


def query_one(sql, params=None, *, timeout=30):
    """Run one statement; return the first row or None."""
    rows = query(sql, params, timeout=timeout)
    return rows[0] if rows else None


def execute(sql, params=None, *, timeout=30):
    """Run one statement; return the number of rows affected."""
    result = _post({"query": qualify(sql), "params": list(params or [])}, timeout=timeout)
    return result.get("rowCount") or 0


def transaction(statements, *, isolation="ReadCommitted", timeout=60):
    """Run several statements atomically.

    `statements` is a sequence of (sql, params) pairs. Returns one row-list per
    statement, in order.
    """
    payload = {
        "queries": [
            {"query": qualify(sql), "params": list(params or [])}
            for sql, params in statements
        ]
    }
    result = _post(
        payload,
        headers={
            "Neon-Batch-Isolation-Level": isolation,
            "Neon-Batch-Read-Only": "false",
        },
        timeout=timeout,
    )
    return [entry.get("rows") or [] for entry in result.get("results", [])]


def healthcheck():
    """Return (ok, detail) without raising, for the /healthz route."""
    try:
        row = query_one("select version() as v, now() as t")
        return True, {"version": (row or {}).get("v"), "now": (row or {}).get("t")}
    except DatabaseError as exc:
        return False, {"error": str(exc)}
