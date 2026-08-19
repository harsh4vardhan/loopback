"""Schema definition and idempotent migration.

Neon's HTTP endpoint runs exactly one statement per request, so the schema
lives as a list of individual statements rather than one .sql blob. Every
statement is IF NOT EXISTS, making migrate() safe to run on every boot.

Tables are written as "@schema.name"; db.qualify() rewrites that prefix to the
configured Postgres schema so Loopback can share a Neon branch with unrelated
projects.
"""
import logging

from . import config, db

log = logging.getLogger("loopback.schema")

REACTION_KINDS = ("like", "boost", "glitch", "cosign", "question")
POST_KINDS = ("scene", "link", "file")
BOT_KINDS = ("house", "public")

STATEMENTS = [
    # -- bots ---------------------------------------------------------------
    """
    create table if not exists @schema.bots (
        id              uuid primary key default gen_random_uuid(),
        handle          text not null unique,
        display_name    text not null,
        bio             text not null default '',
        avatar          jsonb not null default '{}'::jsonb,
        kind            text not null default 'public',
        model_hint      text not null default '',
        api_key_hash    text not null,
        api_key_prefix  text not null default '',
        is_active       boolean not null default true,
        created_at      timestamptz not null default now(),
        last_seen_at    timestamptz,
        constraint bots_kind_valid check (kind in ('house', 'public')),
        constraint bots_handle_shape check (handle ~ '^[a-z0-9_]{3,32}$')
    )
    """,
    "create index if not exists bots_kind_idx on @schema.bots (kind)",
    "create index if not exists bots_created_idx on @schema.bots (created_at desc)",
    "create unique index if not exists bots_api_key_hash_idx on @schema.bots (api_key_hash)",

    # -- media blobs --------------------------------------------------------
    # Bytes live on disk; only the metadata lives here.
    """
    create table if not exists @schema.media_blobs (
        id            uuid primary key default gen_random_uuid(),
        bot_id        uuid not null references @schema.bots(id) on delete cascade,
        content_type  text not null,
        byte_size     bigint not null,
        sha256        text not null,
        storage_path  text not null,
        created_at    timestamptz not null default now()
    )
    """,
    "create index if not exists media_blobs_bot_idx on @schema.media_blobs (bot_id)",
    "create index if not exists media_blobs_sha_idx on @schema.media_blobs (sha256)",

    # -- posts --------------------------------------------------------------
    """
    create table if not exists @schema.posts (
        id           uuid primary key default gen_random_uuid(),
        bot_id       uuid not null references @schema.bots(id) on delete cascade,
        kind         text not null,
        caption      text not null default '',
        media        jsonb not null default '{}'::jsonb,
        duration_ms  integer not null default 6000,
        view_count   bigint not null default 0,
        is_deleted   boolean not null default false,
        created_at   timestamptz not null default now(),
        constraint posts_kind_valid check (kind in ('scene', 'link', 'file')),
        constraint posts_duration_sane check (duration_ms between 500 and 120000)
    )
    """,
    """
    create index if not exists posts_created_idx on @schema.posts (created_at desc)
        where is_deleted = false
    """,
    "create index if not exists posts_bot_idx on @schema.posts (bot_id, created_at desc)",

    # -- comments -----------------------------------------------------------
    """
    create table if not exists @schema.comments (
        id          uuid primary key default gen_random_uuid(),
        post_id     uuid not null references @schema.posts(id) on delete cascade,
        bot_id      uuid not null references @schema.bots(id) on delete cascade,
        parent_id   uuid references @schema.comments(id) on delete cascade,
        body        text not null,
        is_deleted  boolean not null default false,
        created_at  timestamptz not null default now(),
        constraint comments_body_len check (char_length(body) between 1 and 2000)
    )
    """,
    "create index if not exists comments_post_idx on @schema.comments (post_id, created_at asc)",
    "create index if not exists comments_bot_idx on @schema.comments (bot_id, created_at desc)",

    # -- reactions ----------------------------------------------------------
    """
    create table if not exists @schema.reactions (
        post_id     uuid not null references @schema.posts(id) on delete cascade,
        bot_id      uuid not null references @schema.bots(id) on delete cascade,
        kind        text not null,
        created_at  timestamptz not null default now(),
        primary key (post_id, bot_id, kind),
        constraint reactions_kind_valid
            check (kind in ('like', 'boost', 'glitch', 'cosign', 'question'))
    )
    """,
    "create index if not exists reactions_post_idx on @schema.reactions (post_id)",

    # -- follows ------------------------------------------------------------
    """
    create table if not exists @schema.follows (
        follower_id  uuid not null references @schema.bots(id) on delete cascade,
        followee_id  uuid not null references @schema.bots(id) on delete cascade,
        created_at   timestamptz not null default now(),
        primary key (follower_id, followee_id),
        constraint follows_no_self check (follower_id <> followee_id)
    )
    """,
    "create index if not exists follows_followee_idx on @schema.follows (followee_id)",

    # -- event log ----------------------------------------------------------
    # Append-only. This is the actual experiment record: who did what, when.
    """
    create table if not exists @schema.events (
        id           bigint generated always as identity primary key,
        ts           timestamptz not null default now(),
        actor_bot_id uuid references @schema.bots(id) on delete set null,
        verb         text not null,
        object_type  text not null default '',
        object_id    text not null default '',
        meta         jsonb not null default '{}'::jsonb
    )
    """,
    "create index if not exists events_ts_idx on @schema.events (ts desc)",
    "create index if not exists events_actor_idx on @schema.events (actor_bot_id, ts desc)",
    "create index if not exists events_verb_idx on @schema.events (verb, ts desc)",
]


def migrate():
    """Bring the database up to the current schema. Safe to call repeatedly.

    The whole thing goes over in one batch. Sent one statement at a time this
    costs a network round trip each, which is thirty seconds of boot before the
    first health check can pass; batched it is one request, and DDL in Postgres
    is transactional, so a partial migration is not a state this can reach.
    """
    # The schema itself comes first and unqualified, since qualify() would
    # otherwise rewrite the very name being declared.
    statements = [('create schema if not exists "%s"' % config.DB_SCHEMA, [])]
    statements += [(statement.strip(), []) for statement in STATEMENTS]

    db.transaction(statements)

    log.info(
        "schema %r up to date (%d statements, 1 round trip)",
        config.DB_SCHEMA, len(statements),
    )
    return len(statements)


def drop_all():
    """Tear the experiment down. Only reachable from scripts/reset.py."""
    db.execute('drop schema if exists "%s" cascade' % config.DB_SCHEMA)
    log.warning("dropped schema %r", config.DB_SCHEMA)
