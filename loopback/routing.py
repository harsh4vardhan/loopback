"""A small request/response layer over http.server.

Nothing here is clever. It exists so api.py and web.py can declare routes as
decorated functions instead of parsing paths by hand inside a request handler.
"""
import json
import logging
import re
import urllib.parse

log = logging.getLogger("loopback.routing")

_PARAM = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class HttpError(Exception):
    """Raised by handlers to end a request with a specific status."""

    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


class Request:
    def __init__(self, method, path, query, headers, body, client_ip):
        self.method = method
        self.path = path
        self.query = query
        self.headers = headers
        self.body = body
        self.client_ip = client_ip
        self.params = {}
        self.bot = None  # populated by api.py once authenticated

    def header(self, name, default=None):
        return self.headers.get(name.lower(), default)

    def json(self, *, required=True):
        if not self.body:
            if required:
                raise HttpError(400, "a JSON body is required")
            return {}
        try:
            parsed = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HttpError(400, "body is not valid JSON: %s" % exc) from exc
        if not isinstance(parsed, dict):
            raise HttpError(400, "body must be a JSON object")
        return parsed

    def q(self, name, default=None):
        values = self.query.get(name)
        return values[0] if values else default

    def q_int(self, name, default):
        raw = self.q(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default


class Response:
    def __init__(self, status=200, body=b"", headers=None, content_type=None):
        self.status = status
        self.body = body if isinstance(body, (bytes, bytearray)) else str(body).encode()
        self.headers = dict(headers or {})
        if content_type:
            self.headers["Content-Type"] = content_type


def json_response(payload, status=200, headers=None):
    body = json.dumps(payload, default=str, ensure_ascii=False).encode("utf-8")
    merged = {"Content-Type": "application/json; charset=utf-8"}
    merged.update(headers or {})
    return Response(status, body, merged)


def text_response(text, status=200, content_type="text/plain; charset=utf-8"):
    return Response(status, text.encode("utf-8"), {"Content-Type": content_type})


def redirect(location, status=302):
    return Response(status, b"", {"Location": location})


class Router:
    """Literal-segment-first path router with {name} captures."""

    def __init__(self):
        self._routes = []

    def add(self, method, pattern, handler):
        regex = "^" + _PARAM.sub(r"(?P<\1>[^/]+)", pattern.rstrip("/") or "/") + "/?$"
        self._routes.append((method.upper(), re.compile(regex), handler, pattern))
        return handler

    def route(self, method, pattern):
        def decorator(func):
            self.add(method, pattern, func)
            return func
        return decorator

    def get(self, pattern):
        return self.route("GET", pattern)

    def post(self, pattern):
        return self.route("POST", pattern)

    def delete(self, pattern):
        return self.route("DELETE", pattern)

    def extend(self, other):
        """Absorb another router's routes, preserving declaration order."""
        self._routes.extend(other._routes)
        return self

    def resolve(self, method, path):
        """Return (handler, params). Raises HttpError 404/405."""
        normalised = path.rstrip("/") or "/"
        allowed = set()
        for route_method, regex, handler, _pattern in self._routes:
            match = regex.match(normalised)
            if not match:
                continue
            if route_method != method.upper():
                allowed.add(route_method)
                continue
            return handler, {
                key: urllib.parse.unquote(value)
                for key, value in match.groupdict().items()
            }
        if allowed:
            raise HttpError(
                405,
                "method %s not allowed here" % method,
                allow=", ".join(sorted(allowed | {"OPTIONS"})),
            )
        raise HttpError(404, "no route for %s %s" % (method, path))

    def patterns(self):
        return [(m, p) for m, _r, _h, p in self._routes]
