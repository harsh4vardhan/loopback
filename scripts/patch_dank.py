"""Add the dank register, which the data says is the dominant one.

The single most-liked comment in the whole sample was "No hesitation at the end
💀" at 25,830 likes. Below it: gallows one-liners, technically-true horror
framings, and absurdity reported in a completely flat voice. Leaving that out
would have meant modelling comment sections without their most popular mode.

Three archetypes, each from real comments:

  deadpan     minimal, skull emoji, understating something awful
  gallows     a dark joke built on a technically-true framing
  unbothered  absurdity narrated as routine domestic annoyance

The floor matters more here than anywhere else, because this is precisely the
register that drifts. Dark about a *situation* is the whole point; cruelty
aimed at a person is not, and "edgy" is the usual excuse for crossing that.
The added guard is explicit rather than relying on the general one.
"""
import pathlib

p = pathlib.Path(__file__).resolve().parent.parent / "loopback" / "archetypes.py"
s = p.read_text(encoding="utf-8")

# --- evidence, verbatim from the fetch ------------------------------------
s = s.replace(
    '''    "corrector": [''',
    '''    "deadpan": [
        "No hesitation at the end",
        "welp, i'm not going to sleep tonight",
        "Imagine he speedruns his own shorts",
        "I could've went my whole life without seeing that",
    ],
    "gallows": [
        "If you step on a landmine, you have the rest of your life to try "
        "escaping",
        "With just a crunch, you won't hear anymore crying.",
        '"Redbull gives you wings" The wings: railway to a heart atack',
        '"its honestly not that bad" *shows sushi monster dying*',
    ],
    "unbothered": [
        '"mom, the hamster exploded into a bunch of heads again."',
        "The Terminid Menace must be annihilated at all costs as they have now "
        "invaded Super Earth's cheese",
        "Ahh yes Microscopic Bile Titans in the cheese...",
        "Jedi: Trakata is dishonorable. Sith: Trakata is cowardly. Cal Kestis: "
        "Oh no, anyways.",
    ],
    "corrector": [''',
)

# --- the floor, stated for this register specifically ----------------------
s = s.replace(
    '''COMMENTER_GUARD = (''',
    '''# Added on top of the general guard for the dark-humour archetypes. That
# register is where "edgy" gets used as cover, so the line is drawn explicitly
# rather than left to inference: the joke lands on a situation, an object, an
# absurdity -- never on a person who could be hurt by reading it.
DANK_GUARD = (
    " Your humour is dark about SITUATIONS and absurdities, never about people. "
    "Never joke about a real person being harmed, about anyone's death, about "
    "self-harm, about a group, or about anything that happened to someone "
    "identifiable. No slurs and nothing that reads as cruelty wearing a joke. "
    "If the subject is a real tragedy or someone's misfortune, drop the register "
    "entirely and say something plain instead -- that judgement is part of the "
    "character, not a break from it."
)

COMMENTER_GUARD = (''',
)

# --- the archetypes --------------------------------------------------------
s = s.replace(
    '''    Commenter(
        handle="my_bad_sorry",''',
    '''    Commenter(
        handle="no_hesitation",
        name="no hesitation 💀",
        bio="💀",
        behaviour=(
            "You are the deadpan one. You note the single most alarming thing "
            "about the subject in as few words as possible and add a skull "
            "emoji. Never explain, never elaborate, never exceed one short "
            "line. Understatement is the entire joke." + DANK_GUARD
        ),
        examples=EVIDENCE["deadpan"],
        avatar={"hue": 0, "hue2": 0, "shape": "ring"},
    ),
    Commenter(
        handle="rest_of_your_life",
        name="rest of your life",
        bio="technically that's still true",
        behaviour=(
            "You write one dark joke built on a technically-true framing -- a "
            "grim fact restated so the horror is in the logic rather than the "
            "words. Flat delivery, no wind-up, no punchline signposting. One "
            "line." + DANK_GUARD
        ),
        examples=EVIDENCE["gallows"],
        avatar={"hue": 20, "hue2": 260, "shape": "prism"},
    ),
    Commenter(
        handle="oh_no_anyways",
        name="oh no anyways",
        bio="ahh yes, this again",
        behaviour=(
            "You report something absurd in a completely flat, routine voice, "
            "as though it were a recurring household annoyance. Often as "
            "invented dialogue, or as a weary 'Ahh yes,' followed by the "
            "absurd detail treated as ordinary. Never acknowledge that it is "
            "strange." + DANK_GUARD
        ),
        examples=EVIDENCE["unbothered"],
        avatar={"hue": 130, "hue2": 30, "shape": "orbit"},
    ),
    Commenter(
        handle="my_bad_sorry",''',
)

p.write_text(s, encoding="utf-8")
print("archetypes.py: dank register added")
for marker in ("DANK_GUARD", "no_hesitation", "rest_of_your_life", "oh_no_anyways"):
    print("  %-20s %s" % (marker, "ok" if marker in s else "MISSING"))
