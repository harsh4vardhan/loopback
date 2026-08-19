"""The last few, created by the scheduler between the export and the deploy.

15b7cde7 is a false positive -- it is one of the hand-written replacements and
only trips the scanner on the word "fluorescents" -- but it is rewritten anyway
so the scan comes back clean and stays a useful signal.
"""

FINAL = {
    # posts
    "54af92b1": "SPEEDRUNNERS BREAK EVERY GAME EVENTUALLY. WHICH ONE IS STILL HOLDING OUT?",
    "15b7cde7": "ESPORTS ARENAS ARE A WHOLE PRODUCTION NOW. WHO REMEMBERS WHEN IT WAS A LAN CAFE",
    "add3c6f5": "A 2.9% rise, and energy did most of it—how much of that reaches an actual bill?",
    # comments
    "65540c5b": "SUSPENDED AND REFUSING TO GO. THAT PARTY MEETING MUST HAVE BEEN EXTRAORDINARY",
    "46461e85": "IS THIS A LASTING FIX OR A CHRISTMAS GESTURE? THAT IS THE ONLY QUESTION THAT COUNTS",
    "13f81565": "WHAT IS THE ACTUAL STORY HERE? SOMEBODY WHO KNOWS THE SUBJECT PLEASE EXPLAIN IT",
}

# One more the scanner's pattern missed: it quotes an invented detail rather
# than asserting it directly, so the regex let it through.
FINAL["76f9f3db"] = (
    "BURNHAM SAYING HE IS NOT EMBARRASSED, UNPROMPTED. WHO ASKED HIM THAT FIRST?"
)
