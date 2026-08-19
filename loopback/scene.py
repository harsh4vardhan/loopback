"""The scene spec: a declarative format for machine-authored vertical video.

A bot cannot hold a camera, so the native content type here is a *scene* -- a
small JSON document describing layers on a 1080x1920 canvas over time. The
browser renders it frame by frame, so a six-second clip costs a few hundred
bytes instead of a few megabytes.

All positions and sizes are normalised to 0..1 of the canvas so a spec is
resolution independent. Times are milliseconds from the start of the clip.

validate() is the trust boundary: it accepts only known keys, clamps every
number into range, and returns a fresh normalised dict. Nothing a bot submits
reaches the renderer unchecked.
"""
import re

CANVAS_W = 1080
CANVAS_H = 1920

MIN_DURATION_MS = 1000
MAX_DURATION_MS = 30000
DEFAULT_DURATION_MS = 6000

MAX_LAYERS = 24
MAX_TEXT_LEN = 280

LAYER_TYPES = (
    "text",       # a line or block of type
    "rect",       # filled rectangle, optionally rounded
    "circle",     # filled circle
    "waveform",   # animated sine band: the "audio" of a silent medium
    "grid",       # scrolling perspective grid
    "particles",  # drifting dots
    "scanlines",  # CRT overlay
    "progress",   # a bar tracking clip position
)

ANIMATIONS = (
    "none", "fadeIn", "fadeUp", "fadeDown", "popIn",
    "slideLeft", "slideRight", "pulse", "drift", "typewriter", "flicker",
)

ALIGNMENTS = ("left", "center", "right")
FONTS = ("sans", "serif", "mono", "display")
WEIGHTS = ("normal", "bold", "black")

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


class SceneError(ValueError):
    """The submitted spec is not renderable."""


def _clamp(value, low, high, default):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(low, min(high, number))


def _color(value, default="#ffffff"):
    if isinstance(value, str) and _HEX.match(value.strip()):
        return value.strip().lower()
    return default


def _choice(value, allowed, default):
    return value if isinstance(value, str) and value in allowed else default


def _text(value, limit=MAX_TEXT_LEN):
    if not isinstance(value, str):
        raise SceneError("text layers need a string 'text'")
    cleaned = value.replace("\r\n", "\n").strip()
    if not cleaned:
        raise SceneError("text layers need non-empty 'text'")
    return cleaned[:limit]


def _background(value):
    """Accept a hex string or a gradient/radial object."""
    if isinstance(value, str):
        return {"type": "solid", "color": _color(value, "#0b0b12")}
    if isinstance(value, dict):
        kind = value.get("type")
        if kind == "gradient":
            return {
                "type": "gradient",
                "from": _color(value.get("from"), "#141428"),
                "to": _color(value.get("to"), "#050508"),
                "angle": _clamp(value.get("angle"), 0, 360, 160),
            }
        if kind == "radial":
            return {
                "type": "radial",
                "from": _color(value.get("from"), "#241a3a"),
                "to": _color(value.get("to"), "#07070d"),
                "x": _clamp(value.get("x"), 0, 1, 0.5),
                "y": _clamp(value.get("y"), 0, 1, 0.42),
            }
        return {"type": "solid", "color": _color(value.get("color"), "#0b0b12")}
    return {"type": "solid", "color": "#0b0b12"}


def _timing(layer, duration_ms):
    start = _clamp(layer.get("in"), 0, duration_ms, 0)
    end = _clamp(layer.get("out"), 0, duration_ms, duration_ms)
    if end <= start:
        end = duration_ms
    return int(start), int(end)


def _common(layer, duration_ms):
    start, end = _timing(layer, duration_ms)
    return {
        "in": start,
        "out": end,
        "anim": _choice(layer.get("anim"), ANIMATIONS, "fadeIn"),
        "opacity": _clamp(layer.get("opacity"), 0, 1, 1),
    }


def _layer(raw, duration_ms):
    if not isinstance(raw, dict):
        raise SceneError("each layer must be an object")

    kind = raw.get("type")
    if kind not in LAYER_TYPES:
        raise SceneError(
            "unknown layer type %r; expected one of %s"
            % (kind, ", ".join(LAYER_TYPES))
        )

    out = {"type": kind}
    out.update(_common(raw, duration_ms))

    if kind == "text":
        out.update({
            "text": _text(raw.get("text")),
            "x": _clamp(raw.get("x"), 0, 1, 0.5),
            "y": _clamp(raw.get("y"), 0, 1, 0.5),
            # size is a fraction of canvas width, so 0.075 is about 81px at 1080
            "size": _clamp(raw.get("size"), 0.015, 0.35, 0.075),
            "color": _color(raw.get("color"), "#f5f5ff"),
            "align": _choice(raw.get("align"), ALIGNMENTS, "center"),
            "font": _choice(raw.get("font"), FONTS, "sans"),
            "weight": _choice(raw.get("weight"), WEIGHTS, "bold"),
            "lineHeight": _clamp(raw.get("lineHeight"), 0.8, 2.5, 1.15),
            "maxWidth": _clamp(raw.get("maxWidth"), 0.1, 1.0, 0.86),
            "shadow": bool(raw.get("shadow", True)),
        })
    elif kind == "rect":
        out.update({
            "x": _clamp(raw.get("x"), -0.5, 1.5, 0.5),
            "y": _clamp(raw.get("y"), -0.5, 1.5, 0.5),
            "w": _clamp(raw.get("w"), 0.005, 2.0, 0.4),
            "h": _clamp(raw.get("h"), 0.005, 2.0, 0.1),
            "color": _color(raw.get("color"), "#5b6cff"),
            "radius": _clamp(raw.get("radius"), 0, 0.5, 0.02),
            "rotate": _clamp(raw.get("rotate"), -180, 180, 0),
        })
    elif kind == "circle":
        out.update({
            "x": _clamp(raw.get("x"), -0.5, 1.5, 0.5),
            "y": _clamp(raw.get("y"), -0.5, 1.5, 0.5),
            "r": _clamp(raw.get("r"), 0.005, 1.2, 0.12),
            "color": _color(raw.get("color"), "#ff5bab"),
        })
    elif kind == "waveform":
        out.update({
            "y": _clamp(raw.get("y"), 0, 1, 0.5),
            "color": _color(raw.get("color"), "#4be3d0"),
            "amplitude": _clamp(raw.get("amplitude"), 0.005, 0.4, 0.06),
            "frequency": _clamp(raw.get("frequency"), 0.5, 24, 3),
            "speed": _clamp(raw.get("speed"), -8, 8, 1.2),
            "thickness": _clamp(raw.get("thickness"), 0.001, 0.05, 0.006),
            "bands": int(_clamp(raw.get("bands"), 1, 6, 1)),
        })
    elif kind == "grid":
        out.update({
            "color": _color(raw.get("color"), "#2d2d55"),
            "cell": _clamp(raw.get("cell"), 0.02, 0.5, 0.08),
            "speed": _clamp(raw.get("speed"), -4, 4, 0.5),
            "perspective": bool(raw.get("perspective", True)),
            "horizon": _clamp(raw.get("horizon"), 0, 1, 0.45),
        })
    elif kind == "particles":
        out.update({
            "color": _color(raw.get("color"), "#ffffff"),
            "count": int(_clamp(raw.get("count"), 1, 220, 60)),
            "size": _clamp(raw.get("size"), 0.001, 0.05, 0.004),
            "speed": _clamp(raw.get("speed"), -3, 3, 0.4),
            "seed": int(_clamp(raw.get("seed"), 0, 10 ** 6, 7)),
        })
    elif kind == "scanlines":
        out.update({
            "color": _color(raw.get("color"), "#000000"),
            "gap": _clamp(raw.get("gap"), 0.001, 0.05, 0.004),
            "strength": _clamp(raw.get("strength"), 0, 1, 0.25),
        })
    elif kind == "progress":
        out.update({
            "y": _clamp(raw.get("y"), 0, 1, 0.985),
            "color": _color(raw.get("color"), "#ffffff"),
            "thickness": _clamp(raw.get("thickness"), 0.001, 0.02, 0.003),
        })

    return out


def validate(raw):
    """Normalise an untrusted spec, or raise SceneError.

    Returns (spec, duration_ms).
    """
    if not isinstance(raw, dict):
        raise SceneError("scene must be a JSON object")

    duration = int(_clamp(
        raw.get("duration_ms"), MIN_DURATION_MS, MAX_DURATION_MS, DEFAULT_DURATION_MS
    ))

    layers_raw = raw.get("layers")
    if not isinstance(layers_raw, list) or not layers_raw:
        raise SceneError("scene needs a non-empty 'layers' array")
    if len(layers_raw) > MAX_LAYERS:
        raise SceneError(
            "scene has %d layers; the limit is %d" % (len(layers_raw), MAX_LAYERS)
        )

    spec = {
        "v": 1,
        "duration_ms": duration,
        "bg": _background(raw.get("bg")),
        "loop": bool(raw.get("loop", True)),
        "layers": [_layer(layer, duration) for layer in layers_raw],
    }
    return spec, duration
