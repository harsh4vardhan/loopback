"""The tag bar across the top of the feed.

Chips for what the feed is currently about, plus one per footage source so a
viewer can ask for only the real YouTube clips. Tapping a chip refilters the
feed in place; tapping it again clears it.

Source chips are separated from topic chips visually, because they answer
different questions -- "what is this about" versus "where did the video come
from" -- and mixing them into one undifferentiated row makes the bar read as
noise.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent

# --- markup ---------------------------------------------------------------
h = root / "static" / "index.html"
s = h.read_text(encoding="utf-8")
if 'id="topicbar"' not in s:
    s = s.replace(
        '<main id="view" class="view"></main>',
        '<nav id="topicbar" class="topicbar" aria-label="Filter the feed"></nav>\n'
        '\n<main id="view" class="view"></main>',
    )
    h.write_text(s, encoding="utf-8")
    print("index.html: topic bar element")

# --- behaviour ------------------------------------------------------------
a = root / "static" / "app.js"
s = a.read_text(encoding="utf-8")

if "renderTopicBar" not in s:
    s = s.replace(
        "  /* ---------- feed ---------- */",
        '''  /* ---------- topic bar ---------- */

  /* The active filter lives here rather than in the URL: the feed is a scroll
     position as much as a list, and pushing history on every chip tap would
     make the back button walk through filters instead of leaving the feed. */
  var activeFilter = { topic: null, source: null };

  function filterQuery() {
    var parts = [];
    if (activeFilter.topic) parts.push('topic=' + encodeURIComponent(activeFilter.topic));
    if (activeFilter.source) parts.push('source=' + encodeURIComponent(activeFilter.source));
    return parts.length ? '&' + parts.join('&') : '';
  }

  function renderTopicBar() {
    var bar = document.getElementById('topicbar');
    if (!bar) return;

    api('/topics?hours=48&limit=18').then(function (data) {
      var tags = data.topics || [];
      if (!tags.length) { bar.hidden = true; return; }
      bar.hidden = false;
      bar.innerHTML = '';

      function chip(label, kind, value, count) {
        var el_ = el('button', 'chip' + (kind === 'source' ? ' is-source' : ''));
        el_.type = 'button';
        el_.appendChild(el('span', 'chip-label', label));
        if (count) el_.appendChild(el('span', 'chip-count', compact(count)));

        var active = (kind === 'source')
          ? activeFilter.source === value
          : activeFilter.topic === value;
        if (active) el_.classList.add('is-active');

        el_.addEventListener('click', function () {
          /* Tapping the active chip clears it, so the bar is a toggle rather
             than a one-way trip that needs a separate reset control. */
          if (kind === 'source') {
            activeFilter.source = active ? null : value;
          } else {
            activeFilter.topic = active ? null : value;
          }
          renderTopicBar();
          renderFeed();
        });
        return el_;
      }

      if (activeFilter.topic || activeFilter.source) {
        var clear = el('button', 'chip is-clear');
        clear.type = 'button';
        clear.appendChild(el('span', 'chip-label', 'all'));
        clear.addEventListener('click', function () {
          activeFilter = { topic: null, source: null };
          renderTopicBar();
          renderFeed();
        });
        bar.appendChild(clear);
      }

      /* Sources first: "show me only the real YouTube clips" is the most
         common thing someone wants from this bar. */
      tags.filter(function (t) { return t.kind === 'source'; })
        .forEach(function (t) {
          bar.appendChild(chip(t.tag, 'source', t.tag, t.count));
        });

      tags.filter(function (t) { return t.kind !== 'source'; })
        .forEach(function (t) {
          bar.appendChild(chip(t.tag, 'topic', t.tag, t.count));
        });
    }).catch(function () { bar.hidden = true; });
  }

  /* ---------- feed ---------- */''',
    )

    # Both feed fetches carry the filter.
    s = s.replace(
        "    var q = '/feed?mode=algorithmic&limit=8' +\n"
        "      (feedState.cursor ? '&cursor=' + encodeURIComponent(feedState.cursor) : '');",
        "    var q = '/feed?mode=algorithmic&limit=8' + filterQuery() +\n"
        "      (feedState.cursor ? '&cursor=' + encodeURIComponent(feedState.cursor) : '');",
    )
    s = s.replace(
        "    api('/feed?mode=algorithmic&limit=8').then(function (data) {",
        "    api('/feed?mode=algorithmic&limit=8' + filterQuery()).then(function (data) {",
    )

    # An empty filtered feed needs to say so, or it reads as the site being broken.
    s = s.replace(
        '''      if (!data.posts.length) {
        view.className = 'view';
        view.innerHTML =
          '<div class="empty"><div class="big">the feed is empty</div>' +''',
        '''      if (!data.posts.length) {
        view.className = 'view';
        if (activeFilter.topic || activeFilter.source) {
          view.innerHTML =
            '<div class="empty"><div class="big">nothing under that tag yet</div>' +
            '<p>The bots have not posted about ' +
            (activeFilter.topic || activeFilter.source) +
            ' recently. Pick another tag, or tap it again to clear.</p></div>';
          return;
        }
        view.innerHTML =
          '<div class="empty"><div class="big">the feed is empty</div>' +''',
    )

    # The bar belongs to the feed, not to the profile or api pages.
    s = s.replace(
        "  function renderFeed() {\n    setActiveNav('feed');",
        "  function renderFeed() {\n    setActiveNav('feed');\n"
        "    var bar = document.getElementById('topicbar');\n"
        "    if (bar) bar.hidden = false;",
    )
    for page in ("renderBots", "renderAbout", "renderCreate", "renderProfile"):
        s = s.replace(
            "  function %s(" % page,
            "  function %s(" % page,
        )
    s = s.replace(
        "  function teardown() {",
        "  function hideTopicBar() {\n"
        "    var bar = document.getElementById('topicbar');\n"
        "    if (bar) bar.hidden = true;\n"
        "  }\n\n"
        "  function teardown() {",
    )
    s = s.replace(
        "  function route() {\n    teardown();\n    var path = window.location.pathname;",
        "  function route() {\n    teardown();\n    var path = window.location.pathname;\n"
        "    if (path !== '/' && path !== '') hideTopicBar();",
    )
    s = s.replace(
        "    if (path === '/' || path === '') return renderFeed();",
        "    if (path === '/' || path === '') { renderTopicBar(); return renderFeed(); }",
    )

    a.write_text(s, encoding="utf-8")
    print("app.js: topic bar wired")

# --- style ----------------------------------------------------------------
c = root / "static" / "style.css"
s = c.read_text(encoding="utf-8")
if ".topicbar" not in s:
    s += '''

/* ---------- topic bar ---------- */
/* Sits under the header, over the feed. Scrolls horizontally rather than
   wrapping, because a bar that changes height shifts the whole feed. */
.topicbar {
  position: fixed;
  top: var(--topbar-h);
  left: 0; right: 0;
  z-index: 35;
  display: flex;
  gap: 7px;
  padding: 8px 14px 10px;
  overflow-x: auto;
  scrollbar-width: none;
  background: linear-gradient(180deg, rgba(8,8,12,.88), rgba(8,8,12,0));
  -webkit-overflow-scrolling: touch;
}
.topicbar::-webkit-scrollbar { display: none; }
.topicbar[hidden] { display: none; }

.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: rgba(16,16,24,.78);
  backdrop-filter: blur(6px);
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--muted);
  white-space: nowrap;
  transition: border-color .15s, color .15s, background .15s;
}
.chip:hover { color: var(--ink); border-color: var(--accent); }
.chip.is-active {
  color: #fff;
  background: var(--accent);
  border-color: var(--accent);
}
.chip-count { font-size: 9.5px; opacity: .7; }

/* Source chips answer a different question from topic chips -- where the
   footage came from, not what it is about -- so they read differently. */
.chip.is-source { border-style: dashed; color: #c3caff; }
.chip.is-source.is-active { border-style: solid; background: #4a56d6; }
.chip.is-clear { border-color: var(--accent-2); color: var(--accent-2); }
'''
    c.write_text(s, encoding="utf-8")
    print("style.css: chips")

for f, marker in ((h, "topicbar"), (a, "renderTopicBar"), (c, ".chip")):
    print("  %-14s %s" % (f.name, "ok" if marker in f.read_text(encoding="utf-8") else "MISSING"))
