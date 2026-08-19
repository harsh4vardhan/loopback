"""Keep the bots away from subjects this format cannot treat properly.

The news wire brings real headlines, and some of them are about people being
killed. This platform pairs a subject with generic stock footage and a persona
voice -- an all-caps enthusiast, a sceptic making jokes. There is no version of
that which is acceptable over a report of a child's death, and the failure
would not be the model's: it would be mine for handing it that subject.

So subjects naming death, atrocity, violence against people, or abuse are
filtered out before any bot sees them. This is not a topic ban on seriousness;
politics, policy, economics, science, disputes and elections all pass. It is a
recognition that a form built for scroll-stopping clips cannot carry a body
count, and the honest response is not to attempt it.

Assignments also shift toward current affairs, which is what makes the feed
worth arguing with.
"""
import pathlib

# --- trends: filter, applied at the source --------------------------------
t = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "trends.py"
s = t.read_text(encoding="utf-8")

if "_UNSUITABLE" not in s:
    s = s.replace(
        '''# Wikipedia's most-read list is full of scaffolding pages that are not subjects.''',
        '''# Subjects this format cannot do justice to. A bot here reacts in a persona
# voice over stock footage; that is fine for an election result or an energy
# bill, and indefensible over someone's death. Filtered before any bot sees the
# subject, so no prompt has to talk a model out of it afterwards.
_UNSUITABLE = re.compile(
    r"\\b(kill(ed|ing|s)?|dead|death(s)?|died|dies|murder(ed|s)?|massacre|"
    r"atrocit(y|ies)|genocide|execut(ed|ion)|shot dead|stabb(ed|ing)|"
    r"terror(ism|ist)?|bomb(ing|ed)?|airstrike|shooting|gunman|hostage|"
    r"casualt(y|ies)|fatal|funeral|mourn(s|ing)?|abuse(d)?|assault(ed)?|"
    r"rape(d)?|trafficking|suicide|overdose|famine|starv(e|ing|ation)|"
    r"crash kills|toll rises|bodies|injur(ed|ies))\\b",
    re.I,
)


def suitable(subject):
    """False when a subject should not be handed to a persona."""
    return not _UNSUITABLE.search(str(subject or ""))


# Wikipedia's most-read list is full of scaffolding pages that are not subjects.''',
        1,
    )

# Apply it wherever a pool is assembled.
s = s.replace(
    '''    # A narrow category is often empty on a given day -- nothing gaming-related
    # trends every hour. Fall back within the category first, so a gaming bot
    # gets a gaming subject rather than whatever happened to be popular.''',
    '''    # Drop anything this format cannot treat with the seriousness it needs.
    pool = [item for item in pool if suitable(item.get("subject"))]

    # A narrow category is often empty on a given day -- nothing gaming-related
    # trends every hour. Fall back within the category first, so a gaming bot
    # gets a gaming subject rather than whatever happened to be popular.''',
)

t.write_text(s, encoding="utf-8")
print("trends.py: unsuitable-subject filter added")

# --- personas: weight toward current affairs -------------------------------
p = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "bots" / "personas.py"
s = p.read_text(encoding="utf-8")

SHIFTS = [
    # driftwave: culture -> news, but keeps its quiet register
    ('    trend_category = "culture"\n', '    trend_category = "news"\n'),
    # ledger: the numbers one belongs on politics
    ('    trend_category = "news"\n    topics = ("attention", "counting things", "what people looked at")\n',
     '    trend_category = "politics"\n'
     '    topics = ("public spending", "polling", "who benefits", "the small print")\n'),
]
for old, new in SHIFTS:
    if old in s:
        s = s.replace(old, new, 1)
        print("  shifted: %s" % old.strip().split("\n")[0])
    else:
        print("  SHIFT ANCHOR MISSING: %s" % old.strip().split("\n")[0][:50])

p.write_text(s, encoding="utf-8")
print("personas.py: assignments shifted toward current affairs")
