"""Stop cutting sentences off mid-word.

A clout turn ended "Who's truly blind her" -- the 220-character cap fell in the
middle of "here". Every caption and comment on the platform goes through the
same path, so this has been quietly clipping words everywhere; it is just most
obvious when the line is supposed to land as a mic drop.

Truncation now backs up to the last sentence end inside the limit, and failing
that to the last word boundary. A line that stops slightly early reads as
deliberate; one that stops mid-word reads as broken.
"""
import pathlib

p = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "llm.py"
s = p.read_text(encoding="utf-8")

s = s.replace(
    '''def _clean(text, max_chars):
    """Models like to wrap short copy in quotes or prefix it with a label."""
    cleaned = text.strip().split("\\n")[0].strip()
    cleaned = _LABEL_PREFIX.sub("", cleaned)
    cleaned = cleaned.strip().strip('"').strip("'").strip()
    return cleaned[:max_chars] if cleaned else ""''',
    '''def _truncate(text, limit):
    """Cut to a sentence end, or failing that a word boundary.

    Slicing at an exact character count lands mid-word often enough to be
    noticeable, and a line that ends "Who's truly blind her" reads as a bug
    rather than as brevity.
    """
    if len(text) <= limit:
        return text

    window = text[:limit]

    # Prefer ending on a complete sentence, but only if that keeps most of it.
    for mark in (". ", "! ", "? ", ".", "!", "?"):
        cut = window.rfind(mark)
        if cut > limit * 0.6:
            return window[:cut + len(mark)].strip()

    cut = window.rfind(" ")
    if cut > limit * 0.5:
        return window[:cut].rstrip(" ,;:-")
    return window.rstrip(" ,;:-")


def _clean(text, max_chars):
    """Models like to wrap short copy in quotes or prefix it with a label."""
    cleaned = text.strip().split("\\n")[0].strip()
    cleaned = _LABEL_PREFIX.sub("", cleaned)
    cleaned = cleaned.strip().strip('"').strip("'").strip()
    return _truncate(cleaned, max_chars) if cleaned else ""''',
)

p.write_text(s, encoding="utf-8")
print("llm.py: truncation respects sentence and word boundaries")

# Prove it on the exact failure, plus the cases that should be untouched.
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import importlib
from loopback import llm
importlib.reload(llm)

CASES = [
    ("You say patterns only matter if someone is paying, but that is just "
     "lazy. You think real value is measured by attention? No. Who is truly "
     "blind here", 220),
    ("Short enough already.", 220),
    ("onelongwordwithnospacesatallthatcannotbebrokenanywhere", 20),
]
for text, limit in CASES:
    out = llm._truncate(text, limit)
    print("  %3d -> %3d  %r" % (len(text), len(out), out[-46:]))
