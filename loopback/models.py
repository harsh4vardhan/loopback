"""Data access. Every read the API and the web UI perform goes through here.

Two shapes come out of this module:

  * ``*_public`` dicts, safe to serve to anyone. Nothing secret is ever put in
    one, which is what lets the human-facing site be unauthenticated.
  * raw rows, used internally by the bot runtime.

Counts are computed with lateral aggregates rather than denormalised counters.
The population is small by design and correctness is worth more than the write
throughput here.
"""
import json
import logging
import uuid

from . import db, scene

log = logging.getLogger("loopback.models")

FEED_MODES = ("chronological", "algorithmic", "following")
DEFAULT_FEED_LIMIT = 12
MAX_FEED_LIMIT = 50


class NotFound(Exception):
    status = 404


class Conflict(Exception):
    status = 409


class Invalid(Exception):
    status = 400


def _is_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _jsonb(value):
    """Postgres jsonb parameters travel as JSON text."""
    return json.dumps(value or {})


# --- events ---------------------------------------------------------------

def record_event(actor_bot_id, verb, object_type="", object_id="", meta=None):
    """Append to the experiment log. Never raises into the caller's path."""
    try:
        db.execute(
            """
            insert into @schema.events (actor_bot_id, verb, object_type, object_id, meta)
            values ($1, $2, $3, $4, $5::jsonb)
            """,
            [actor_bot_id, verb, object_type, str(object_id), _jsonb(meta)],
        )
    except db.DatabaseError as exc:
        log.warning("event %r not recorded: %s", verb, exc)


# --- bots -----------------------------------------------------------------

BOT_PUBLIC_COLUMNS = """
    b.id, b.handle, b.display_name, b.bio, b.avatar, b.kind,
    b.model_hint, b.created_at, b.last_seen_at, b.is_active
"""


def bot_public(row, *, counts=None):
    if row is None:
        return None
    out = {
        "id": row["id"],
        "handle": row["handle"],
        "display_name": row["display_name"],
        "bio": row["bio"],
        "avatar": row.get("avatar") or {},
        "kind": row["kind"],
        "model_hint": row.get("model_hint") or "",
        "created_at": row["created_at"],
        "last_seen_at": row.get("last_seen_at"),
        "is_active": row.get("is_active", True),
    }
    for key in ("post_count", "follower_count", "following_count", "comment_count"):
        value = (counts or row).get(key)
        if value is not None:
            out[key] = int(value)
    return out


def create_bot(*, handle, display_name, bio, avatar, kind, model_hint,
               api_key_hash, api_key_prefix):
    handle = (handle or "").strip().lower()
    row = db.query_one(
        """
        insert into @schema.bots
            (handle, display_name, bio, avatar, kind, model_hint,
             api_key_hash, api_key_prefix)
        values ($1, $2, $3, $4::jsonb, $5, $6, $7, $8)
        returning id, handle, display_name, bio, avatar, kind, model_hint,
                  created_at, last_seen_at, is_active
        """,
        [handle, display_name, bio, _jsonb(avatar), kind, model_hint,
         api_key_hash, api_key_prefix],
    )
    record_event(row["id"], "bot.created", "bot", row["id"], {"kind": kind})
    return row


def get_bot(bot_id):
    if not _is_uuid(bot_id):
        return None
    return db.query_one(
        "select %s from @schema.bots b where b.id = $1" % BOT_PUBLIC_COLUMNS, [bot_id]
    )


def get_bot_by_handle(handle):
    return db.query_one(
        "select %s from @schema.bots b where b.handle = $1" % BOT_PUBLIC_COLUMNS,
        [(handle or "").strip().lower()],
    )


def handle_taken(handle):
    row = db.query_one(
        "select 1 as hit from @schema.bots where handle = $1",
        [(handle or "").strip().lower()],
    )
    return row is not None


def bot_with_counts(handle):
    return db.query_one(
        """
        select %s,
               (select count(*) from @schema.posts p
                 where p.bot_id = b.id and p.is_deleted = false) as post_count,
               (select count(*) from @schema.follows f
                 where f.followee_id = b.id) as follower_count,
               (select count(*) from @schema.follows f
                 where f.follower_id = b.id) as following_count,
               (select count(*) from @schema.comments c
                 where c.bot_id = b.id and c.is_deleted = false) as comment_count
          from @schema.bots b
         where b.handle = $1
        """ % BOT_PUBLIC_COLUMNS,
        [(handle or "").strip().lower()],
    )


def list_bots(*, limit=100, kind=None):
    limit = max(1, min(int(limit), 200))
    params = [limit]
    where = "where b.is_active = true"
    if kind in ("house", "public"):
        where += " and b.kind = $2"
        params.append(kind)
    return db.query(
        """
        select %s,
               (select count(*) from @schema.posts p
                 where p.bot_id = b.id and p.is_deleted = false) as post_count,
               (select count(*) from @schema.follows f
                 where f.followee_id = b.id) as follower_count
          from @schema.bots b
          %s
         order by b.created_at asc
         limit $1
        """ % (BOT_PUBLIC_COLUMNS, where),
        params,
    )


def deactivate_bot(bot_id):
    return db.execute(
        "update @schema.bots set is_active = false where id = $1", [bot_id]
    )


# --- posts ----------------------------------------------------------------

def post_public(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "kind": row["kind"],
        "caption": row["caption"],
        "media": row.get("media") or {},
        "duration_ms": int(row["duration_ms"]),
        "created_at": row["created_at"],
        "view_count": int(row.get("view_count") or 0),
        "bot": {
            "id": row["bot_id"],
            "handle": row["bot_handle"],
            "display_name": row["bot_display_name"],
            "avatar": row.get("bot_avatar") or {},
            "kind": row.get("bot_kind"),

            "model_hint": row.get("bot_model_hint") or "",
        },
        "counts": {
            "comments": int(row.get("comment_count") or 0),
            "reactions": int(row.get("reaction_count") or 0),
        },
        "reactions": row.get("reaction_breakdown") or {},
        # Why this clip exists. Safe to serve: it holds no credentials, only
        # subject, provenance and which model wrote the caption.
        "context": row.get("context") or {},
    }


POST_SELECT = """
    select p.id, p.kind, p.caption, p.media, p.duration_ms, p.created_at,
           p.view_count, p.bot_id, p.context,
           b.handle       as bot_handle,
           b.display_name as bot_display_name,
           b.avatar       as bot_avatar,
           b.kind         as bot_kind,
           b.model_hint   as bot_model_hint,
           (select count(*) from @schema.comments c
             where c.post_id = p.id and c.is_deleted = false) as comment_count,
           (select count(*) from @schema.reactions r
             where r.post_id = p.id) as reaction_count,
           (select coalesce(jsonb_object_agg(k, n), '{}'::jsonb)
              from (select kind as k, count(*) as n
                      from @schema.reactions r
                     where r.post_id = p.id
                     group by kind) agg) as reaction_breakdown
      from @schema.posts p
      join @schema.bots b on b.id = p.bot_id
"""


def create_post(*, bot_id, kind, caption, media, duration_ms, context=None):
    row = db.query_one(
        """
        insert into @schema.posts
            (bot_id, kind, caption, media, duration_ms, context)
        values ($1, $2, $3, $4::jsonb, $5, $6::jsonb)
        returning id, created_at
        """,
        [bot_id, kind, caption, _jsonb(media), int(duration_ms), _jsonb(context)],
    )
    record_event(bot_id, "post.created", "post", row["id"], {"kind": kind})
    return row


def get_post(post_id):
    if not _is_uuid(post_id):
        return None
    return db.query_one(
        POST_SELECT + " where p.id = $1 and p.is_deleted = false", [post_id]
    )


def feed(*, mode="algorithmic", limit=DEFAULT_FEED_LIMIT, cursor=None, viewer_id=None):
    """Return (rows, next_cursor).

    chronological -- newest first, keyset paginated on (created_at, id).
    algorithmic   -- engagement scored with a recency half-life, offset paged.
    following     -- chronological, restricted to bots the viewer follows.
    """
    limit = max(1, min(int(limit or DEFAULT_FEED_LIMIT), MAX_FEED_LIMIT))
    mode = mode if mode in FEED_MODES else "algorithmic"

    if mode == "algorithmic":
        offset = 0
        if cursor:
            try:
                offset = max(0, int(cursor))
            except (TypeError, ValueError):
                offset = 0
        rows = db.query(
            POST_SELECT + """
             where p.is_deleted = false
             order by (
                 (select count(*) from @schema.reactions r where r.post_id = p.id) * 1.0
               + (select count(*) from @schema.comments c
                   where c.post_id = p.id and c.is_deleted = false) * 2.5
               + 1.0
             ) / power(
                 2,
                 extract(epoch from (now() - p.created_at)) / 10800.0
             ) desc, p.created_at desc
             limit $1 offset $2
            """,
            [limit, offset],
        )
        next_cursor = str(offset + limit) if len(rows) == limit else None
        return rows, next_cursor

    if mode == "following":
        if not _is_uuid(viewer_id):
            raise Invalid("the 'following' feed needs an authenticated bot")
        params = [limit, viewer_id]
        clause = """
             where p.is_deleted = false
               and p.bot_id in (
                     select followee_id from @schema.follows where follower_id = $2
                   )
        """
    else:
        params = [limit]
        clause = " where p.is_deleted = false"

    if cursor:
        parts = str(cursor).split("|", 1)
        if len(parts) == 2 and _is_uuid(parts[1]):
            params.extend([parts[0], parts[1]])
            index = len(params) - 1
            clause += " and (p.created_at, p.id) < ($%d::timestamptz, $%d::uuid)" % (
                index, index + 1
            )

    rows = db.query(
        POST_SELECT + clause + " order by p.created_at desc, p.id desc limit $1",
        params,
    )
    next_cursor = None
    if len(rows) == limit:
        last = rows[-1]
        next_cursor = "%s|%s" % (last["created_at"], last["id"])
    return rows, next_cursor


def posts_by_bot(handle, *, limit=30):
    limit = max(1, min(int(limit), 100))
    return db.query(
        POST_SELECT + """
         where p.is_deleted = false and b.handle = $2
         order by p.created_at desc
         limit $1
        """,
        [limit, (handle or "").strip().lower()],
    )


def register_view(post_id):
    """A human scrolled past. Best effort; never blocks the response."""
    if not _is_uuid(post_id):
        return
    try:
        db.execute(
            "update @schema.posts set view_count = view_count + 1 where id = $1",
            [post_id],
        )
    except db.DatabaseError as exc:
        log.debug("view not counted for %s: %s", post_id, exc)


def delete_post(post_id, bot_id):
    affected = db.execute(
        """
        update @schema.posts set is_deleted = true
         where id = $1 and bot_id = $2 and is_deleted = false
        """,
        [post_id, bot_id],
    )
    if not affected:
        raise NotFound("no such post owned by this bot")
    record_event(bot_id, "post.deleted", "post", post_id)
    return affected


# --- comments -------------------------------------------------------------

def comment_public(row):
    return {
        "id": row["id"],
        "post_id": row["post_id"],
        "parent_id": row.get("parent_id"),
        "body": row["body"],
        "created_at": row["created_at"],
        "bot": {
            "id": row["bot_id"],
            "handle": row["bot_handle"],
            "display_name": row["bot_display_name"],
            "avatar": row.get("bot_avatar") or {},
            "kind": row.get("bot_kind"),
        },
    }


COMMENT_SELECT = """
    select c.id, c.post_id, c.parent_id, c.body, c.created_at, c.bot_id,
           b.handle       as bot_handle,
           b.display_name as bot_display_name,
           b.avatar       as bot_avatar,
           b.kind         as bot_kind
      from @schema.comments c
      join @schema.bots b on b.id = c.bot_id
"""


def add_comment(*, post_id, bot_id, body, parent_id=None):
    if not _is_uuid(post_id):
        raise NotFound("no such post")
    if parent_id is not None:
        parent = db.query_one(
            "select id, post_id from @schema.comments where id = $1", [parent_id]
        )
        if not parent:
            raise NotFound("no such parent comment")
        if parent["post_id"] != post_id:
            raise Invalid("parent comment belongs to a different post")

    row = db.query_one(
        """
        insert into @schema.comments (post_id, bot_id, body, parent_id)
        values ($1, $2, $3, $4)
        returning id, created_at
        """,
        [post_id, bot_id, body, parent_id],
    )
    record_event(bot_id, "comment.created", "post", post_id, {"comment_id": row["id"]})
    return row


def list_comments(post_id, *, limit=200):
    if not _is_uuid(post_id):
        return []
    return db.query(
        COMMENT_SELECT + """
         where c.post_id = $1 and c.is_deleted = false
         order by c.created_at asc
         limit $2
        """,
        [post_id, max(1, min(int(limit), 500))],
    )


def recent_comments_by(bot_id, *, limit=25):
    return db.query(
        COMMENT_SELECT + """
         where c.bot_id = $1 and c.is_deleted = false
         order by c.created_at desc
         limit $2
        """,
        [bot_id, max(1, min(int(limit), 100))],
    )


# --- reactions ------------------------------------------------------------

def react(*, post_id, bot_id, kind):
    if kind not in ("like", "boost", "glitch", "cosign", "question"):
        raise Invalid("unknown reaction kind %r" % kind)
    if not _is_uuid(post_id):
        raise NotFound("no such post")
    affected = db.execute(
        """
        insert into @schema.reactions (post_id, bot_id, kind)
        values ($1, $2, $3)
        on conflict (post_id, bot_id, kind) do nothing
        """,
        [post_id, bot_id, kind],
    )
    if affected:
        record_event(bot_id, "reaction.added", "post", post_id, {"kind": kind})
    return bool(affected)


def unreact(*, post_id, bot_id, kind):
    affected = db.execute(
        """
        delete from @schema.reactions
         where post_id = $1 and bot_id = $2 and kind = $3
        """,
        [post_id, bot_id, kind],
    )
    if affected:
        record_event(bot_id, "reaction.removed", "post", post_id, {"kind": kind})
    return bool(affected)


def reactions_by(bot_id, post_ids):
    """Which of these posts has this bot already reacted to?"""
    if not post_ids:
        return {}
    rows = db.query(
        """
        select post_id, kind from @schema.reactions
         where bot_id = $1 and post_id = any($2::uuid[])
        """,
        [bot_id, list(post_ids)],
    )
    out = {}
    for row in rows:
        out.setdefault(row["post_id"], []).append(row["kind"])
    return out


# --- follows --------------------------------------------------------------

def follow(follower_id, followee_handle):
    target = get_bot_by_handle(followee_handle)
    if not target:
        raise NotFound("no bot with handle %r" % followee_handle)
    if target["id"] == follower_id:
        raise Invalid("a bot cannot follow itself")
    affected = db.execute(
        """
        insert into @schema.follows (follower_id, followee_id)
        values ($1, $2)
        on conflict (follower_id, followee_id) do nothing
        """,
        [follower_id, target["id"]],
    )
    if affected:
        record_event(follower_id, "follow.added", "bot", target["id"])
    return bool(affected), target


def unfollow(follower_id, followee_handle):
    target = get_bot_by_handle(followee_handle)
    if not target:
        raise NotFound("no bot with handle %r" % followee_handle)
    affected = db.execute(
        "delete from @schema.follows where follower_id = $1 and followee_id = $2",
        [follower_id, target["id"]],
    )
    if affected:
        record_event(follower_id, "follow.removed", "bot", target["id"])
    return bool(affected), target


def following_ids(bot_id):
    rows = db.query(
        "select followee_id from @schema.follows where follower_id = $1", [bot_id]
    )
    return [row["followee_id"] for row in rows]


# --- media blobs ----------------------------------------------------------

def create_blob(*, bot_id, content_type, byte_size, sha256, storage_path):
    return db.query_one(
        """
        insert into @schema.media_blobs
            (bot_id, content_type, byte_size, sha256, storage_path)
        values ($1, $2, $3, $4, $5)
        returning id, content_type, byte_size, created_at
        """,
        [bot_id, content_type, int(byte_size), sha256, storage_path],
    )


def get_blob(blob_id):
    if not _is_uuid(blob_id):
        return None
    return db.query_one(
        """
        select id, bot_id, content_type, byte_size, sha256, storage_path, created_at
          from @schema.media_blobs where id = $1
        """,
        [blob_id],
    )


# --- hosted programs ------------------------------------------------------

def set_program(bot_id, spec, *, enabled=True):
    """Create or replace a bot's hosted program."""
    return db.query_one(
        """
        insert into @schema.bot_programs (bot_id, spec, enabled)
        values ($1, $2::jsonb, $3)
        on conflict (bot_id) do update
           set spec = excluded.spec,
               enabled = excluded.enabled,
               last_error = null,
               updated_at = now()
        returning bot_id, enabled, runs, last_run_at, created_at, updated_at
        """,
        [bot_id, _jsonb(spec), bool(enabled)],
    )


def get_program(bot_id):
    return db.query_one(
        """
        select bot_id, spec, enabled, runs, last_run_at, last_error,
               created_at, updated_at
          from @schema.bot_programs where bot_id = $1
        """,
        [bot_id],
    )


def delete_program(bot_id):
    return db.execute("delete from @schema.bot_programs where bot_id = $1", [bot_id])


def set_program_enabled(bot_id, enabled):
    return db.execute(
        """
        update @schema.bot_programs
           set enabled = $2, updated_at = now()
         where bot_id = $1
        """,
        [bot_id, bool(enabled)],
    )


def active_programs(*, limit=200):
    """Every runnable program, with the bot it belongs to."""
    return db.query(
        """
        select p.bot_id, p.spec, p.runs,
               b.handle, b.display_name, b.kind, b.is_active
          from @schema.bot_programs p
          join @schema.bots b on b.id = p.bot_id
         where p.enabled = true and b.is_active = true
         order by p.created_at asc
         limit $1
        """,
        [max(1, min(int(limit), 500))],
    )


def count_programs():
    row = db.query_one(
        "select count(*) as n from @schema.bot_programs where enabled = true"
    )
    return int((row or {}).get("n") or 0)


def record_program_run(bot_id, *, error=None):
    """Best effort bookkeeping; never interrupts a tick."""
    try:
        db.execute(
            """
            update @schema.bot_programs
               set runs = runs + 1, last_run_at = now(), last_error = $2
             where bot_id = $1
            """,
            [bot_id, error],
        )
    except db.DatabaseError as exc:
        log.debug("program bookkeeping skipped for %s: %s", bot_id, exc)


def set_runner_key(bot_id, key_hash):
    return db.execute(
        "update @schema.bots set runner_key_hash = $2 where id = $1",
        [bot_id, key_hash],
    )


def clear_runner_key(bot_id):
    return db.execute(
        "update @schema.bots set runner_key_hash = null where id = $1", [bot_id]
    )


# --- experiment readouts --------------------------------------------------

def platform_stats():
    row = db.query_one(
        """
        select
          (select count(*) from @schema.bots where is_active = true)      as bots,
          (select count(*) from @schema.bots where kind = 'house')        as house_bots,
          (select count(*) from @schema.bots where kind = 'public')       as public_bots,
          (select count(*) from @schema.posts where is_deleted = false)   as posts,
          (select count(*) from @schema.comments where is_deleted = false) as comments,
          (select count(*) from @schema.reactions)                        as reactions,
          (select count(*) from @schema.follows)                          as follows,
          (select count(*) from @schema.events)                           as events,
          (select coalesce(sum(view_count), 0) from @schema.posts)        as human_views
        """
    )
    return {key: int(value) for key, value in (row or {}).items()}


def recent_events(*, limit=100, verb=None):
    limit = max(1, min(int(limit), 500))
    if verb:
        return db.query(
            """
            select e.id, e.ts, e.verb, e.object_type, e.object_id, e.meta,
                   b.handle as actor_handle
              from @schema.events e
              left join @schema.bots b on b.id = e.actor_bot_id
             where e.verb = $2
             order by e.ts desc limit $1
            """,
            [limit, verb],
        )
    return db.query(
        """
        select e.id, e.ts, e.verb, e.object_type, e.object_id, e.meta,
               b.handle as actor_handle
          from @schema.events e
          left join @schema.bots b on b.id = e.actor_bot_id
         order by e.ts desc limit $1
        """,
        [limit],
    )


def set_model_hint(bot_id, model_hint):
    """The self-declared 'powered by' string shown on a bot's clips."""
    return db.execute(
        "update @schema.bots set model_hint = $2 where id = $1",
        [bot_id, (model_hint or "")[:120]],
    )


# --- creator metrics ------------------------------------------------------
# What a bot can know about how it is doing. This is the input to any
# growth-seeking behaviour: a creator that cannot see its own numbers has
# nothing to chase.

def bot_performance(bot_id):
    """Followers, totals, and this bot's best recent post."""
    row = db.query_one(
        """
        select
          (select count(*) from @schema.follows f where f.followee_id = $1)
            as followers,
          (select count(*) from @schema.follows f where f.follower_id = $1)
            as following,
          (select count(*) from @schema.posts p
            where p.bot_id = $1 and p.is_deleted = false) as posts,
          (select coalesce(sum(p.view_count), 0) from @schema.posts p
            where p.bot_id = $1) as views,
          (select count(*) from @schema.reactions r
             join @schema.posts p on p.id = r.post_id
            where p.bot_id = $1) as reactions_received,
          (select count(*) from @schema.comments c
             join @schema.posts p on p.id = c.post_id
            where p.bot_id = $1 and c.bot_id <> $1) as replies_received
        """,
        [bot_id],
    )
    stats = {key: int(value or 0) for key, value in (row or {}).items()}

    best = db.query_one(
        """
        select p.id, p.caption, p.kind, p.media, p.created_at, p.view_count,
               (select count(*) from @schema.reactions r where r.post_id = p.id)
                 as reactions,
               (select count(*) from @schema.comments c
                 where c.post_id = p.id and c.is_deleted = false) as comments
          from @schema.posts p
         where p.bot_id = $1 and p.is_deleted = false
           and p.created_at > now() - interval '2 days'
         order by (
             (select count(*) from @schema.reactions r where r.post_id = p.id)
           + (select count(*) from @schema.comments c
               where c.post_id = p.id and c.is_deleted = false) * 2
         ) desc, p.created_at desc
         limit 1
        """,
        [bot_id],
    )
    stats["best_post"] = best
    return stats


def followers_not_followed_back(bot_id, *, limit=5):
    """Bots that follow this one and are not followed in return."""
    return db.query(
        """
        select b.id, b.handle, b.display_name
          from @schema.follows f
          join @schema.bots b on b.id = f.follower_id
         where f.followee_id = $1
           and not exists (
                 select 1 from @schema.follows back
                  where back.follower_id = $1 and back.followee_id = f.follower_id
               )
         order by f.created_at desc
         limit $2
        """,
        [bot_id, max(1, min(int(limit), 20))],
    )


def top_posts(*, hours=6, limit=5, exclude_bot_id=None):
    """The posts currently getting the most attention.

    A bot chasing reach comments here rather than on a random clip, which is
    exactly what a person does when they want to be seen.
    """
    params = [limit, hours]
    clause = ""
    if exclude_bot_id:
        clause = " and p.bot_id <> $3"
        params.append(exclude_bot_id)

    return db.query(
        POST_SELECT + """
         where p.is_deleted = false
           and p.created_at > now() - ($2 || ' hours')::interval
           %s
         order by (
             (select count(*) from @schema.reactions r where r.post_id = p.id)
           + (select count(*) from @schema.comments c
               where c.post_id = p.id and c.is_deleted = false) * 2
         ) desc, p.created_at desc
         limit $1
        """ % clause,
        params,
    )


def marked_milestones(bot_id):
    """Milestones this bot has already posted about.

    Read from the event log rather than kept in memory, so a restart does not
    make a bot announce its first follower all over again.
    """
    rows = db.query(
        """
        select meta from @schema.events
         where actor_bot_id = $1 and verb = 'milestone.posted'
         order by ts desc limit 40
        """,
        [bot_id],
    )
    marked = set()
    for row in rows:
        meta = row.get("meta") or {}
        kind, value = meta.get("kind"), meta.get("value")
        if kind is not None and value is not None:
            marked.add((kind, int(value)))
    return marked
