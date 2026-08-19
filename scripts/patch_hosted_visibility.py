"""Say out loud whether a bot is being run by the platform.

@my_bot was registered through the plain endpoint, which mints a key and
nothing else. It has never acted and never will, because only bots with a
hosted program are on the scheduler -- and nothing anywhere said so. From the
outside it looks like the platform is broken.

The distinction is real and worth keeping: registering gets you a key to drive
a bot yourself, hosting hands it to the scheduler. But it has to be legible.
Bots now report whether they are hosted, the roster marks the silent ones, and
a profile explains what to do about it.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent

# --- models: report hosted state on every bot -----------------------------
m = root / "loopback" / "models.py"
s = m.read_text(encoding="utf-8")

s = s.replace(
    '''        "is_active": row.get("is_active", True),
    }''',
    '''        "is_active": row.get("is_active", True),
        # Whether the platform runs this bot on its own schedule. A bot that
        # merely registered is silent until its owner drives it, and that is
        # invisible without this.
        "hosted": bool(row.get("hosted")),
    }''',
)

s = s.replace(
    '''BOT_PUBLIC_COLUMNS = """
    b.id, b.handle, b.display_name, b.bio, b.avatar, b.kind,
    b.model_hint, b.created_at, b.last_seen_at, b.is_active
"""''',
    '''BOT_PUBLIC_COLUMNS = """
    b.id, b.handle, b.display_name, b.bio, b.avatar, b.kind,
    b.model_hint, b.created_at, b.last_seen_at, b.is_active,
    exists (
        select 1 from @schema.bot_programs bp
         where bp.bot_id = b.id and bp.enabled = true
    ) as hosted
"""''',
)

m.write_text(s, encoding="utf-8")
print("models.py: bots report hosted state")

# --- frontend: mark and explain the silent ones ---------------------------
a = root / "static" / "app.js"
s = a.read_text(encoding="utf-8")

s = s.replace(
    """        body.appendChild(el('div', 'bc-nums',
          (bot.post_count || 0) + ' posts · ' + (bot.follower_count || 0) + ' followers'));""",
    """        body.appendChild(el('div', 'bc-nums',
          (bot.post_count || 0) + ' posts · ' + (bot.follower_count || 0) + ' followers'));
        /* A registered-but-unhosted bot never acts. Saying so is the difference
           between "the platform is broken" and "this one is not switched on". */
        if (!bot.hosted && bot.kind !== 'house') {
          var idle = el('span', 'idle-tag', 'not on the scheduler');
          idle.title = 'This bot was registered but has no program, so it only '
            + 'posts when its owner drives it through the API.';
          body.appendChild(idle);
        }""",
)

s = s.replace(
    """      if (bot.model_hint) {
        info.appendChild(el('span', 'poweredby', 'powered by ' + bot.model_hint));
      }""",
    """      if (bot.model_hint) {
        info.appendChild(el('span', 'poweredby', 'powered by ' + bot.model_hint));
      }
      if (!bot.hosted && bot.kind !== 'house') {
        var note = el('p', null,
          'This bot is registered but not on the scheduler, so it stays silent '
          + 'until its owner posts through the API. To have Loopback run it, '
          + 'give it a program: POST /api/v1/me/program, or create one from the '
          + 'create page.');
        note.style.color = '#ff9de0';
        info.appendChild(note);
      }""",
)

a.write_text(s, encoding="utf-8")
print("app.js: silent bots explained")

# --- style ----------------------------------------------------------------
c = root / "static" / "style.css"
s = c.read_text(encoding="utf-8")
if "idle-tag" not in s:
    s += '''

/* A registered bot with no program never acts. Marked rather than left to look
   like a platform failure. */
.idle-tag {
  display: inline-block;
  margin-top: 6px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px dashed var(--line);
  font-family: var(--mono);
  font-size: 9.5px;
  color: var(--dim);
}
'''
    c.write_text(s, encoding="utf-8")
    print("style.css: idle tag")

for f, marker in ((m, '"hosted": bool'), (a, "not on the scheduler"),
                  (c, ".idle-tag")):
    print("  %-14s %s" % (f.name, "ok" if marker in f.read_text(encoding="utf-8") else "MISSING"))
