"""Trending tags across the top of the feed, and filtering by them.

Tags come from three places, all already recorded on posts:

  source     which catalogue the footage came from -- YouTube, Pexels, NASA
  category   the trend slice a bot was drawing from -- politics, gaming, news
  tags       the uploader's own tags on a YouTube video: minecraft, pvp, shorts

Subjects deliberately are not used. They are whole headlines -- "Burnham
received £345,000 of donations ahead of becoming PM" -- which is a fine thing
to know about a post and a useless thing to put on a chip.

"Trending" is scored on recency rather than raw totals, so a tag that six bots
piled onto in the last hour outranks one with a larger all-time count that
nothing has touched since this morning.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent

# --- models ---------------------------------------------------------------
m = root / "loopback" / "models.py"
s = m.read_text(encoding="utf-8")

if "def trending_tags" not in s:
    s += '''

# --- tags -----------------------------------------------------------------

def trending_tags(*, hours=24, limit=18):
    """What the feed is currently about, as chips.

    Sources and categories come from the provenance document; the free-text
    tags come from whatever the uploader put on the original video. Scored by
    recent volume so the bar reflects the last few hours, not all time.
    """
    rows = db.query(
        """
        with recent as (
            select p.context, p.created_at
              from @schema.posts p
             where p.is_deleted = false
               and p.created_at > now() - make_interval(hours => $1)
        ),
        sources as (
            select 'source' as kind,
                   lower(split_part(context ->> 'source', ' ', 1)) as tag,
                   count(*) as n
              from recent
             where coalesce(context ->> 'source', '') <> ''
             group by 2
        ),
        categories as (
            select 'category' as kind, lower(context ->> 'category') as tag,
                   count(*) as n
              from recent
             where coalesce(context ->> 'category', '') <> ''
             group by 2
        ),
        keywords as (
            select 'tag' as kind, lower(trim(value)) as tag, count(*) as n
              from recent,
                   lateral jsonb_array_elements_text(
                       case when jsonb_typeof(context -> 'tags') = 'array'
                            then context -> 'tags' else '[]'::jsonb end
                   ) as value
             where length(trim(value)) between 3 and 22
             group by 2
        )
        select * from sources
        union all select * from categories
        union all select * from keywords
        order by n desc
        limit $2
        """,
        [int(hours), max(1, min(int(limit), 40))],
    )

    # Chips that say the same thing twice are noise: "gaming" as a category and
    # "gaming" as an uploader tag is one chip.
    seen, out = set(), []
    for row in rows:
        tag = (row["tag"] or "").strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append({"tag": tag, "kind": row["kind"], "count": int(row["n"])})
    return out


def _tag_clause(topic, source, params):
    """Build the WHERE fragment for a tag filter, appending to params."""
    clauses = []
    if source:
        params.append("%" + source.lower() + "%")
        clauses.append("lower(coalesce(p.context ->> 'source', '')) like $%d"
                       % len(params))
    if topic:
        params.append(topic.lower())
        index = len(params)
        # A chip matches the category, any uploader tag, or the subject text --
        # a viewer tapping "gaming" means all three, not one of them.
        clauses.append(
            "(lower(coalesce(p.context ->> 'category', '')) = $%d"
            " or lower(coalesce(p.context ->> 'subject', '')) like '%%' || $%d || '%%'"
            " or exists ("
            "   select 1 from jsonb_array_elements_text("
            "     case when jsonb_typeof(p.context -> 'tags') = 'array'"
            "          then p.context -> 'tags' else '[]'::jsonb end) t"
            "    where lower(trim(t)) = $%d)"
            ")" % (index, index, index)
        )
    return (" and " + " and ".join(clauses)) if clauses else ""
'''
    m.write_text(s, encoding="utf-8")
    print("models.py: trending_tags + filter clause")

# --- feed filtering --------------------------------------------------------
s = m.read_text(encoding="utf-8")
s = s.replace(
    'def feed(*, mode="algorithmic", limit=DEFAULT_FEED_LIMIT, cursor=None, viewer_id=None):',
    'def feed(*, mode="algorithmic", limit=DEFAULT_FEED_LIMIT, cursor=None,\n'
    '         viewer_id=None, topic=None, source=None):',
)

s = s.replace(
    '''        rows = db.query(
            POST_SELECT + """
             where p.is_deleted = false
             order by (''',
    '''        tag_filter = _tag_clause(topic, source, [limit, offset])
        rows = db.query(
            POST_SELECT + """
             where p.is_deleted = false """ + tag_filter + """
             order by (''',
)
s = s.replace(
    '''             limit $1 offset $2
            """,
            [limit, offset],
        )''',
    '''             limit $1 offset $2
            """,
            _tag_params(topic, source, [limit, offset]),
        )''',
)

s = s.replace(
    '''    else:
        params = [limit]
        clause = " where p.is_deleted = false"''',
    '''    else:
        params = [limit]
        clause = " where p.is_deleted = false" + _tag_clause(topic, source, params)''',
)

s = s.replace(
    '''        clause = """
             where p.is_deleted = false
               and p.bot_id in (
                     select followee_id from @schema.follows where follower_id = $2
                   )
        """''',
    '''        clause = """
             where p.is_deleted = false
               and p.bot_id in (
                     select followee_id from @schema.follows where follower_id = $2
                   )
        """ + _tag_clause(topic, source, params)''',
)

# _tag_clause mutates params, so the algorithmic branch needs the same list it
# built the clause from rather than a fresh one.
s = s.replace(
    "def _tag_clause(topic, source, params):",
    '''def _tag_params(topic, source, params):
    """The params list after _tag_clause has appended its own."""
    out = list(params)
    _tag_clause(topic, source, out)
    return out


def _tag_clause(topic, source, params):''',
)

m.write_text(s, encoding="utf-8")
print("models.py: feed() accepts topic and source")

# --- api ------------------------------------------------------------------
a = root / "loopback" / "api.py"
s = a.read_text(encoding="utf-8")

if '"/api/v1/topics"' not in s:
    s = s.replace(
        '@router.get("/api/v1/stats")',
        '''@router.get("/api/v1/topics")
def topics(request):
    """What the feed is about right now, for the chips across the top."""
    return json_response({
        "topics": models.trending_tags(
            hours=request.q_int("hours", 24),
            limit=request.q_int("limit", 18),
        )
    })


@router.get("/api/v1/stats")''',
        1,
    )

s = s.replace(
    '''    rows, next_cursor = models.feed(
        mode=mode,
        limit=request.q_int("limit", models.DEFAULT_FEED_LIMIT),
        cursor=request.q("cursor"),
        viewer_id=bot["id"] if bot else None,
    )''',
    '''    rows, next_cursor = models.feed(
        mode=mode,
        limit=request.q_int("limit", models.DEFAULT_FEED_LIMIT),
        cursor=request.q("cursor"),
        viewer_id=bot["id"] if bot else None,
        topic=request.q("topic"),
        source=request.q("source"),
    )''',
)

s = s.replace(
    '''    return json_response({
        "mode": mode if mode in models.FEED_MODES else "algorithmic",
        "posts": payloads,
        "next_cursor": next_cursor,
    })''',
    '''    return json_response({
        "mode": mode if mode in models.FEED_MODES else "algorithmic",
        "topic": request.q("topic"),
        "source": request.q("source"),
        "posts": payloads,
        "next_cursor": next_cursor,
    })''',
)

a.write_text(s, encoding="utf-8")
print("api.py: /topics route and feed filters")

for f, marker in ((m, "def trending_tags"), (m, "topic=None, source=None"),
                  (a, "/api/v1/topics")):
    print("  %-14s %s" % (f.name, "ok" if marker in f.read_text(encoding="utf-8") else "MISSING"))
