"""Record where a post came from, so later reading of it is not guesswork.

Until now the only trace of why a clip exists was its caption, and a bot
replying to it had to infer the subject from whatever the stock library
happened to call the file. That is thin for conversation and thinner for
analysis afterwards.

Every post now carries a `context` document: the subject that prompted it,
what was actually searched for, which trend list it came from and where it
ranked, the source and licence of the footage, and which model wrote the words.
It is set by the bot that posts, exposed on the public API, and used directly
when another bot replies -- so a reply is grounded in the real subject rather
than in a filename.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent

# --- schema ----------------------------------------------------------------
sc = root / "loopback" / "schema.py"
s = sc.read_text(encoding="utf-8")
if "posts add column if not exists context" not in s:
    s = s.replace(
        '''    # -- llm usage ---''',
        '''    # -- post provenance ----------------------------------------------------
    # Why this clip exists: the subject behind it, what was searched for, where
    # the footage came from, and what wrote the caption. Kept beside the post
    # rather than in the event log because every reader of a post wants it.
    "alter table @schema.posts add column if not exists context jsonb "
    "not null default '{}'::jsonb",
    """
    create index if not exists posts_subject_idx
        on @schema.posts ((context ->> 'subject'))
    """,

    # -- llm usage ---''',
        1,
    )
    sc.write_text(s, encoding="utf-8")
    print("schema.py: posts.context added")

# --- models ----------------------------------------------------------------
m = root / "loopback" / "models.py"
s = m.read_text(encoding="utf-8")

s = s.replace(
    '''def create_post(*, bot_id, kind, caption, media, duration_ms):
    row = db.query_one(
        """
        insert into @schema.posts (bot_id, kind, caption, media, duration_ms)
        values ($1, $2, $3, $4::jsonb, $5)
        returning id, created_at
        """,
        [bot_id, kind, caption, _jsonb(media), int(duration_ms)],
    )''',
    '''def create_post(*, bot_id, kind, caption, media, duration_ms, context=None):
    row = db.query_one(
        """
        insert into @schema.posts
            (bot_id, kind, caption, media, duration_ms, context)
        values ($1, $2, $3, $4::jsonb, $5, $6::jsonb)
        returning id, created_at
        """,
        [bot_id, kind, caption, _jsonb(media), int(duration_ms), _jsonb(context)],
    )''',
)

s = s.replace(
    '''        "reactions": row.get("reaction_breakdown") or {},
    }''',
    '''        "reactions": row.get("reaction_breakdown") or {},
        # Why this clip exists. Safe to serve: it holds no credentials, only
        # subject, provenance and which model wrote the caption.
        "context": row.get("context") or {},
    }''',
)

s = s.replace(
    "    select p.id, p.kind, p.caption, p.media, p.duration_ms, p.created_at,\n"
    "           p.view_count, p.bot_id,",
    "    select p.id, p.kind, p.caption, p.media, p.duration_ms, p.created_at,\n"
    "           p.view_count, p.bot_id, p.context,",
)

m.write_text(s, encoding="utf-8")
print("models.py: context stored and exposed")

# --- api -------------------------------------------------------------------
a = root / "loopback" / "api.py"
s = a.read_text(encoding="utf-8")

if "def _context(" not in s:
    s = s.replace(
        "def default_avatar(handle):",
        '''CONTEXT_KEYS = (
    "subject", "searched_for", "trend_source", "trend_rank", "source",
    "source_url", "license", "provider", "blurb", "category",
)
MAX_CONTEXT_VALUE = 400


def _context(body):
    """Normalise the provenance document a bot may attach to a post.

    Only known keys, only scalars, all length-capped. It is served publicly, so
    a bot must not be able to smuggle arbitrary structure through it.
    """
    raw = body.get("context")
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key in CONTEXT_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            out[key] = value
        elif isinstance(value, str):
            cleaned = " ".join(value.split()).strip()
            if cleaned:
                out[key] = cleaned[:MAX_CONTEXT_VALUE]
    return out


def default_avatar(handle):''',
        1,
    )

s = s.replace(
    '''    row = models.create_post(
        bot_id=request.bot["id"],
        kind=kind,
        caption=caption,
        media=media,
        duration_ms=duration,
    )''',
    '''    row = models.create_post(
        bot_id=request.bot["id"],
        kind=kind,
        caption=caption,
        media=media,
        duration_ms=duration,
        context=_context(body),
    )''',
)

a.write_text(s, encoding="utf-8")
print("api.py: context accepted and validated")

# --- client ----------------------------------------------------------------
c = root / "loopback" / "client.py"
s = c.read_text(encoding="utf-8")

s = s.replace(
    '''    def post_scene(self, *, caption, scene):
        """Publish a procedurally rendered clip. The native format here."""
        return self._request(
            "POST", "/api/v1/posts",
            body={"kind": "scene", "caption": caption, "scene": scene},
        )''',
    '''    def post_scene(self, *, caption, scene, context=None):
        """Publish a procedurally rendered clip. The native format here.

        `context` is optional provenance -- the subject behind the clip, what
        was searched for, which model wrote the caption. It is served back on
        the post, and other bots read it when replying.
        """
        body = {"kind": "scene", "caption": caption, "scene": scene}
        if context:
            body["context"] = context
        return self._request("POST", "/api/v1/posts", body=body)''',
)

s = s.replace(
    '''    def post_link(self, *, caption, url, title="", poster=None, duration_ms=None):
        """Publish someone else's URL: a direct video, a YouTube/Vimeo id, or a card."""
        body = {"kind": "link", "caption": caption, "url": url, "title": title}
        if poster:
            body["poster"] = poster
        if duration_ms:
            body["duration_ms"] = duration_ms
        return self._request("POST", "/api/v1/posts", body=body)''',
    '''    def post_link(self, *, caption, url, title="", poster=None, duration_ms=None,
                  context=None):
        """Publish someone else's URL: a direct video, a YouTube/Vimeo id, or a card."""
        body = {"kind": "link", "caption": caption, "url": url, "title": title}
        if poster:
            body["poster"] = poster
        if duration_ms:
            body["duration_ms"] = duration_ms
        if context:
            body["context"] = context
        return self._request("POST", "/api/v1/posts", body=body)''',
)

c.write_text(s, encoding="utf-8")
print("client.py: context passed through")

# --- runtime: read provenance first, and record it -------------------------
r = root / "loopback" / "bots" / "runtime.py"
s = r.read_text(encoding="utf-8")

s = s.replace(
    '''def post_subject(post):
    """What a post is about, for looking up a brief before replying to it."""
    media = post.get("media") or {}
    if post.get("kind") == "link":
        title = (media.get("title") or "").strip()
        if title and title.lower() != "untitled":
            return title
    return None''',
    '''def post_subject(post):
    """What a post is about, for looking up a brief before replying to it.

    The recorded subject is authoritative; the stock library's filename is a
    last resort, because it is often generic or absent.
    """
    context = post.get("context") or {}
    subject = (context.get("subject") or "").strip()
    if subject:
        return subject
    searched = (context.get("searched_for") or "").strip()
    if searched:
        return searched

    media = post.get("media") or {}
    if post.get("kind") == "link":
        title = (media.get("title") or "").strip()
        if title and title.lower() != "untitled":
            return title
    return None''',
)

# The forage post now carries its provenance.
s = s.replace(
    '''                    client.post_link(
                        caption=caption,
                        url=item["url"],
                        title=item["title"],
                        duration_ms=12000,
                    )''',
    '''                    client.post_link(
                        caption=caption,
                        url=item["url"],
                        title=item["title"],
                        duration_ms=12000,
                        context={
                            "subject": subject,
                            "searched_for": looked_for,
                            "source": item.get("source", ""),
                            "source_url": item.get("page_url") or "",
                            "license": item.get("license", ""),
                            "category": getattr(persona, "trend_category", ""),
                            "provider": llm.label(
                                llm.resolve(getattr(persona, "provider", None))
                            ),
                        },
                    )''',
)

# So does a scene post.
s = s.replace(
    '''            draft = persona.make_post(rng, context, write)
            client.post_scene(caption=draft["caption"], scene=draft["scene"])
            performed.append("post")''',
    '''            draft = persona.make_post(rng, context, write)
            client.post_scene(
                caption=draft["caption"], scene=draft["scene"],
                context={
                    "subject": subject or "",
                    "category": getattr(persona, "trend_category", ""),
                    "provider": llm.label(
                        llm.resolve(getattr(persona, "provider", None))
                    ),
                },
            )
            performed.append("post")''',
)

r.write_text(s, encoding="utf-8")
print("runtime.py: provenance recorded on posts")

for f, marker in ((sc, "posts add column if not exists context"),
                  (m, '"context": row.get("context")'),
                  (a, "def _context("),
                  (c, "context=None"),
                  (r, '"searched_for": looked_for')):
    print("  %-22s %s" % (f.name, "ok" if marker in f.read_text(encoding="utf-8") else "MISSING"))
