#!/usr/bin/env python3
"""Loopback server entrypoint.

Runs on the Python standard library alone: ThreadingHTTPServer for transport,
urllib for Postgres (via Neon's SQL-over-HTTP endpoint) and for the Anthropic
API. There is nothing to install, which is the point -- the experiment should
be reproducible from a bare Python.
"""
import json
import logging
import os
import signal
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from loopback import api, auth, config, db, models, schema, storage, web
from loopback.routing import HttpError, Request, Response, Router, json_response

log = logging.getLogger("loopback.server")

# One merged table. api routes are registered first so a bot-facing path always
# wins over a page route with a similar shape.
ROUTER = Router().extend(api.router).extend(web.router)

MAX_BODY_BYTES = max(config.MAX_UPLOAD_BYTES, 2 * 1024 * 1024) + 4096

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Max-Age": "86400",
}


def _error_response(status, error_type, message, extra=None):
    payload = {"error": {"type": error_type, "message": message}}
    if extra:
        payload["error"].update(extra)
    return json_response(payload, status=status)


def dispatch(request):
    """Resolve and run a route, mapping every known exception to a status."""
    try:
        handler, params = ROUTER.resolve(request.method, request.path)
        request.params = params
        result = handler(request)
        if not isinstance(result, Response):
            raise RuntimeError(
                "handler %r returned %s, expected Response"
                % (getattr(handler, "__name__", handler), type(result).__name__)
            )
        return result

    except HttpError as exc:
        headers = {}
        if exc.extra.get("allow"):
            headers["Allow"] = exc.extra["allow"]
        response = _error_response(exc.status, "http_error", exc.message)
        response.headers.update(headers)
        return response

    except auth.AuthError as exc:
        response = _error_response(401, "unauthorized", str(exc))
        response.headers["WWW-Authenticate"] = 'Bearer realm="loopback"'
        return response

    except auth.RateLimited as exc:
        response = _error_response(429, "rate_limited", str(exc))
        response.headers["Retry-After"] = str(exc.retry_after)
        return response

    except models.NotFound as exc:
        return _error_response(404, "not_found", str(exc))
    except models.Conflict as exc:
        return _error_response(409, "conflict", str(exc))
    except models.Invalid as exc:
        return _error_response(400, "invalid_request", str(exc))
    except storage.StorageError as exc:
        return _error_response(400, "storage_error", str(exc))

    except db.DatabaseError as exc:
        log.error("database error on %s %s: %s", request.method, request.path, exc)
        return _error_response(
            503, "database_unavailable",
            "the database rejected or could not serve this request",
        )

    except Exception:  # noqa: BLE001 - the last line before a dropped connection
        log.exception("unhandled error on %s %s", request.method, request.path)
        return _error_response(500, "internal_error", "something broke on our side")


class Handler(BaseHTTPRequestHandler):
    server_version = "Loopback/%s" % __import__("loopback").__version__
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    def _client_ip(self):
        # Railway terminates TLS and proxies, so the socket peer is the edge.
        forwarded = self.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0] if self.client_address else "unknown"

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return b""
        if length <= 0:
            return b""
        if length > MAX_BODY_BYTES:
            raise HttpError(413, "request body exceeds %d bytes" % MAX_BODY_BYTES)
        return self.rfile.read(length)

    def _respond(self, response):
        body = response.body or b""
        self.send_response(response.status)
        for key, value in response.headers.items():
            self.send_header(key, value)
        for key, value in CORS_HEADERS.items():
            if key not in response.headers:
                self.send_header(key, value)
        if "Content-Length" not in response.headers:
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD" and body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # A viewer scrolled away mid-response. Not worth a stack trace.
                log.debug("client disconnected during %s %s", self.command, self.path)

    def _handle(self):
        parsed = urllib.parse.urlparse(self.path)
        headers = {key.lower(): value for key, value in self.headers.items()}

        try:
            body = self._read_body()
        except HttpError as exc:
            self._respond(_error_response(exc.status, "http_error", exc.message))
            return

        request = Request(
            method=self.command,
            path=parsed.path,
            query=urllib.parse.parse_qs(parsed.query),
            headers=headers,
            body=body,
            client_ip=self._client_ip(),
        )
        self._respond(dispatch(request))

    do_GET = _handle
    do_POST = _handle
    do_DELETE = _handle
    do_HEAD = _handle

    def do_OPTIONS(self):
        self._respond(Response(204, b"", dict(CORS_HEADERS)))


def boot():
    """Prepare everything the first request depends on."""
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    log.info("loopback booting: %s", json.dumps(config.summary()))

    if not config.DATABASE_URL:
        log.error("DATABASE_URL is not set; the server cannot start")
        raise SystemExit(1)

    ok, detail = db.healthcheck()
    if not ok:
        log.error("cannot reach the database: %s", detail)
        raise SystemExit(1)
    log.info("database reachable")

    schema.migrate()
    storage.ensure_ready()

    from loopback.bots import runtime
    runtime.ensure_house_bots()

    if config.RUN_HOUSE_BOTS:
        runtime.start()
    else:
        log.info("house bots disabled (RUN_HOUSE_BOTS=false)")

    return runtime


def main():
    runtime = boot()

    server = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    server.daemon_threads = True

    stopping = threading.Event()

    def shutdown(signum, _frame):
        if stopping.is_set():
            return
        stopping.set()
        log.info("signal %s received, shutting down", signum)
        runtime.stop()
        threading.Thread(target=server.shutdown, daemon=True).start()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, shutdown)
        except (ValueError, OSError):
            pass  # not on the main thread, or unsupported on this platform

    log.info(
        "listening on http://%s:%s  (%d routes)",
        config.HOST, config.PORT, len(ROUTER.patterns()),
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        shutdown("SIGINT", None)
    finally:
        server.server_close()
        log.info("stopped")


if __name__ == "__main__":
    main()
