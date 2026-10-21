import html
import re
from html.parser import HTMLParser

import agent

ARTICLE = {"title": "On Love & Loss", "link": "https://example.com/a?x=1&utm_source=rss", "source": "The Marginalian", "content": ""}


class TagChecker(HTMLParser):
    """فقط تگ‌هایی که تلگرام می‌پذیرد، و همه بسته شده باشند."""
    allowed = {"b", "i", "a", "blockquote"}

    def __init__(self):
        super().__init__()
        self.stack = []

    def handle_starttag(self, tag, attrs):
        assert tag in self.allowed, tag
        self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack.pop() == tag


def check_html(post):
    checker = TagChecker()
    checker.feed(post)
    assert checker.stack == []


def test_post_escapes_model_output():
    summary = {
        "title": "**عشق** و <فقدان>",
        "hook": "وقتی a < b & c",
        "points": ["- نکتهٔ اول", "۲. نکتهٔ دوم"],
        "reflection": "چه چیزی می‌ماند؟",
        "hashtags": ["خودشناسی", "رابطه‌ها", "#عشق", "روان شناسی", "123"],
    }
    post = agent.build_post(summary, ARTICLE)
    check_html(post)
    assert "**" not in post
    assert "&lt;فقدان&gt;" in post
    assert "a &lt; b &amp; c" in post
    assert "- نکته" not in post and "۲. نکته" not in post
    assert 'href="https://example.com/a?x=1&amp;utm_source=rss"' in post
    assert "#رابطه_ها" in post and "#روان_شناسی" in post and "#عشق" in post
    assert "#123" not in post
    assert agent.CHANNEL_HANDLE in post


def test_post_fits_telegram_limit():
    summary = {"title": "عنوان", "points": ["کلمه " * 300] * 5, "hashtags": []}
    post = agent.build_post(summary, ARTICLE)
    assert agent.telegram_length(post) <= 4096
    check_html(post)


def test_hashtag_fallback_to_source():
    post = agent.build_post({"title": "عنوان", "points": ["نکته"], "hashtags": []}, ARTICLE)
    assert "#The_Marginalian" in post


def test_normalize_link():
    a = agent.normalize_link("https://Example.com/post?utm_source=x#top")
    b = agent.normalize_link("https://example.com/post/")
    assert a == b


def test_parse_json_reply_handles_code_fence():
    assert agent.parse_json_reply('```json\n{"points": ["x"]}\n```') == {"points": ["x"]}
