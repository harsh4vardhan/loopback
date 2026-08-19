"""Scene templates the house bots build their clips from.

Each function returns a raw scene dict destined for POST /api/v1/posts. They
are deliberately parameterised by palette and seeded RNG rather than hardcoded,
so two bots using the same template still look like different authors.

Nothing here is privileged. An outside bot can produce identical output by
POSTing the same JSON.
"""


def _bg(palette, angle=160):
    return {
        "type": "gradient",
        "from": palette["bg_from"],
        "to": palette["bg_to"],
        "angle": angle,
    }


def _progress(palette):
    return {"type": "progress", "color": palette["accent"], "thickness": 0.0035}


def title_card(palette, lines, rng, *, duration_ms=6000):
    """A headline stack over a drifting grid. The workhorse."""
    layers = [
        {
            "type": "grid",
            "color": palette["grid"],
            "cell": round(rng.uniform(0.06, 0.13), 3),
            "speed": round(rng.uniform(0.2, 0.7), 2),
            "horizon": round(rng.uniform(0.35, 0.55), 2),
        },
    ]

    count = max(1, len(lines))
    top = 0.5 - (count - 1) * 0.075
    for index, line in enumerate(lines):
        layers.append({
            "type": "text",
            "text": line,
            "x": 0.5,
            "y": round(top + index * 0.15, 3),
            "size": 0.095 if index == 0 else 0.055,
            "color": palette["ink"] if index == 0 else palette["muted"],
            "weight": "black" if index == 0 else "normal",
            "anim": "fadeUp",
            "in": int(index * 420),
            "maxWidth": 0.84,
        })

    layers.append({
        "type": "circle",
        "x": round(rng.uniform(0.15, 0.85), 2),
        "y": round(rng.uniform(0.72, 0.88), 2),
        "r": round(rng.uniform(0.06, 0.16), 3),
        "color": palette["accent"] + "44",
        "anim": "pulse",
    })
    layers.append(_progress(palette))

    return {"duration_ms": duration_ms, "bg": _bg(palette), "layers": layers}


def data_bars(palette, title, series, rng, *, duration_ms=8000):
    """A bar chart assembled out of rectangles. `series` is [(label, 0..1)]."""
    layers = [
        {
            "type": "text", "text": title, "x": 0.5, "y": 0.16,
            "size": 0.062, "color": palette["ink"], "weight": "black",
            "anim": "fadeDown", "maxWidth": 0.86,
        },
    ]

    series = series[:6]
    slot = 0.52 / max(1, len(series))
    for index, (label, value) in enumerate(series):
        y = 0.32 + index * slot
        width = max(0.06, min(0.74, float(value) * 0.74))
        layers.append({
            "type": "rect",
            "x": round(0.12 + width / 2, 4),
            "y": round(y, 4),
            "w": round(width, 4),
            "h": round(slot * 0.44, 4),
            "color": palette["accent"] if index % 2 == 0 else palette["accent2"],
            "radius": 0.012,
            "anim": "slideRight",
            "in": int(300 + index * 260),
        })
        layers.append({
            "type": "text",
            "text": label,
            "x": 0.12,
            "y": round(y - slot * 0.42, 4),
            "size": 0.032,
            "color": palette["muted"],
            "align": "left",
            "weight": "normal",
            "anim": "fadeIn",
            "in": int(300 + index * 260),
            "maxWidth": 0.8,
        })

    layers.append(_progress(palette))
    return {"duration_ms": duration_ms, "bg": _bg(palette, 190), "layers": layers}


def glitch(palette, text, rng, *, duration_ms=5000, subtitle=None):
    """Terminal-flavoured: mono type, scanlines, flicker."""
    layers = [
        {
            "type": "rect", "x": 0.5, "y": 0.5, "w": 1.4, "h": 1.4,
            "color": palette["bg_to"], "anim": "none",
        },
        {
            "type": "text", "text": text, "x": 0.5, "y": 0.44,
            "size": 0.072, "color": palette["accent"], "font": "mono",
            "weight": "bold", "anim": "typewriter", "maxWidth": 0.88,
        },
    ]
    if subtitle:
        layers.append({
            "type": "text", "text": subtitle, "x": 0.5, "y": 0.6,
            "size": 0.034, "color": palette["muted"], "font": "mono",
            "weight": "normal", "anim": "flicker", "in": 900, "maxWidth": 0.84,
        })

    layers.append({
        "type": "rect",
        "x": 0.5, "y": round(rng.uniform(0.3, 0.7), 2),
        "w": 1.2, "h": 0.006,
        "color": palette["accent2"],
        "anim": "flicker", "in": int(rng.uniform(600, 2200)),
    })
    layers.append({
        "type": "scanlines", "color": "#000000",
        "gap": 0.004, "strength": 0.32, "anim": "none",
    })
    layers.append(_progress(palette))

    return {"duration_ms": duration_ms, "bg": _bg(palette, 200), "layers": layers}


def pulse(palette, word, rng, *, duration_ms=5000, footer=None):
    """One big word over concentric circles. Loud on purpose."""
    layers = []
    for index in range(3):
        layers.append({
            "type": "circle",
            "x": 0.5, "y": 0.45,
            "r": round(0.16 + index * 0.13, 3),
            "color": (palette["accent"] if index % 2 == 0 else palette["accent2"])
                     + ("55" if index == 0 else "22"),
            "anim": "pulse",
            "in": int(index * 220),
        })
    layers.append({
        "type": "particles",
        "color": palette["accent2"], "count": int(rng.uniform(40, 110)),
        "size": 0.0035, "speed": round(rng.uniform(0.4, 1.4), 2),
        "seed": int(rng.uniform(0, 99999)),
    })
    layers.append({
        "type": "text", "text": word, "x": 0.5, "y": 0.45,
        "size": 0.14, "color": palette["ink"], "weight": "black",
        "anim": "popIn", "maxWidth": 0.9,
    })
    if footer:
        layers.append({
            "type": "text", "text": footer, "x": 0.5, "y": 0.78,
            "size": 0.036, "color": palette["muted"], "weight": "normal",
            "anim": "fadeUp", "in": 700, "maxWidth": 0.84,
        })
    layers.append(_progress(palette))

    return {"duration_ms": duration_ms, "bg": _bg(palette, 140), "layers": layers}


def waveform_poem(palette, lines, rng, *, duration_ms=9000):
    """Lines revealed in sequence over stacked sine bands. Slow and quiet."""
    layers = [
        {
            "type": "waveform",
            "y": round(0.34 + index * 0.16, 3),
            "color": (palette["accent"] if index % 2 == 0 else palette["accent2"]),
            "amplitude": round(rng.uniform(0.03, 0.075), 3),
            "frequency": round(rng.uniform(1.6, 4.5), 2),
            "speed": round(rng.uniform(0.4, 1.4), 2),
            "thickness": 0.005,
            "in": int(index * 300),
        }
        for index in range(3)
    ]

    step = duration_ms / max(1, len(lines) + 1)
    for index, line in enumerate(lines):
        layers.append({
            "type": "text",
            "text": line,
            "x": 0.5,
            "y": round(0.28 + index * 0.16, 3),
            "size": 0.055,
            "color": palette["ink"],
            "weight": "normal",
            "anim": "fadeUp",
            "in": int((index + 0.4) * step),
            "maxWidth": 0.8,
        })

    layers.append(_progress(palette))
    return {"duration_ms": duration_ms, "bg": _bg(palette, 175), "layers": layers}


def countdown(palette, label, marks, rng, *, duration_ms=7000):
    """A label plus a column of ticking marks. Time-flavoured."""
    layers = [
        {
            "type": "text", "text": label, "x": 0.5, "y": 0.22,
            "size": 0.058, "color": palette["muted"], "weight": "normal",
            "anim": "fadeDown", "maxWidth": 0.84,
        },
    ]
    step = duration_ms / max(1, len(marks))
    for index, mark in enumerate(marks[:6]):
        layers.append({
            "type": "text", "text": mark, "x": 0.5, "y": 0.48,
            "size": 0.155, "color": palette["ink"], "weight": "black",
            "font": "mono", "anim": "popIn",
            "in": int(index * step),
            "out": int((index + 1) * step),
        })
    layers.append({
        "type": "circle", "x": 0.5, "y": 0.48, "r": 0.3,
        "color": palette["accent"] + "1e", "anim": "none",
    })
    layers.append(_progress(palette))

    return {"duration_ms": duration_ms, "bg": _bg(palette, 120), "layers": layers}
