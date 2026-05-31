"""Offline tests for parsing the HTML form of Takeout watch history."""

from ytdc.history import parse_watch_history
from ytdc.report import build_analysis

# Two watched items on one channel, plus one with no channel link (deleted/ad).
# Mirrors Takeout's MDL markup: a body-1 data cell per entry, with sibling
# text-right / caption cells the parser must ignore.
WATCH_HISTORY_HTML = """<html><body>
<div class="outer-cell"><div class="mdl-grid">
<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">Watched <a href="https://www.youtube.com/watch?v=v1">Vid 1</a><br><a href="https://www.youtube.com/channel/UCalpha">Alpha &amp; Co</a><br>Jan 1, 2023, 1:00:00 AM EST<br></div>
<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1 mdl-typography--text-right"></div>
<div class="content-cell mdl-cell mdl-cell--12-col mdl-typography--caption"><b>Products:</b><br>YouTube</div>
</div></div>
<div class="outer-cell"><div class="mdl-grid">
<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">Watched <a href="https://www.youtube.com/watch?v=v2">Vid 2</a><br><a href="https://www.youtube.com/channel/UCalpha">Alpha &amp; Co</a><br>Mar 1, 2023, 2:30:00 PM EST<br></div>
</div></div>
<div class="outer-cell"><div class="mdl-grid">
<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">Watched a removed video<br>Apr 1, 2023, 3:00:00 PM EST<br></div>
</div></div>
</body></html>
"""


def test_parse_html_watch_history(tmp_path):
    history = tmp_path / "watch-history.html"
    history.write_text(WATCH_HISTORY_HTML)
    channels, unattributable = parse_watch_history(history)

    assert unattributable == 1  # the entry with no /channel/ link
    assert channels["UCalpha"]["views"] == 2
    assert channels["UCalpha"]["name"] == "Alpha & Co"  # html-unescaped
    # localized timestamps parse to sortable ISO, min/max correct (not lexical).
    assert channels["UCalpha"]["first_watched"] == "2023-01-01T01:00:00"
    assert channels["UCalpha"]["last_watched"] == "2023-03-01T14:30:00"


def test_build_analysis_through_html(tmp_path):
    history = tmp_path / "watch-history.html"
    history.write_text(WATCH_HISTORY_HTML)
    subs = tmp_path / "subscriptions.json"
    subs.write_text('[{"channel_id": "UCalpha", "title": "Alpha"}]')
    likes = tmp_path / "likes.json"
    likes.write_text("[]")

    analysis = build_analysis(history, subscriptions_file=subs, likes_file=likes)

    sub = analysis["subscriptions"][0]
    assert sub["watched"] is True
    assert sub["views"] == 2
    assert analysis["unattributable"] == 1
