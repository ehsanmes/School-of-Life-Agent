"""
School of Life Agent
هر بار اجرا: یک مقالهٔ تازه از فیدها انتخاب می‌کند، با هوش مصنوعی خلاصهٔ فارسی می‌سازد
و آن را با قالبی خوانا برای تلگرام در کانال منتشر می‌کند.

اجرای آزمایشی بدون ارسال به تلگرام و بدون تغییر فایل حافظه:
    DRY_RUN=1 python agent.py
"""

import asyncio
import html
import json
import os
import random
import re
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx
from bs4 import BeautifulSoup
from openai import OpenAI
from telegram import Bot, LinkPreviewOptions
from telegram.constants import MessageLimit, ParseMode

# --- 1. CONFIGURATION ---
AVALAI_API_KEY = os.environ.get("AVALAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
AVALAI_BASE_URL = "https://api.avalai.ir/v1"
MODEL_TO_USE = os.environ.get("MODEL", "gpt-4o-mini")
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

CHANNEL_HANDLE = "@momento_lab"

# --- مخزن کامل فیدها ---
LIVE_FEEDS = {
    "The Marginalian": "https://www.themarginalian.org/feed/",
    # بدون اسلش پایانی، سایت پاسخ 403 می‌دهد
    "The School of Life": "https://www.theschooloflife.com/feed/",
    "Scientific American": "http://rss.sciam.com/sciam/mind-and-brain",
}
LOCAL_XML_FILE = "content.xml"  # بانک مقالات پشتیبان
MEMORY_FILE = "_posted_articles.txt"  # فایل حافظه

# بعضی سایت‌ها درخواست‌های بدون User-Agent مرورگر را مسدود می‌کنند
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)
HTTP_TIMEOUT = 30

# اگر متن فید کوتاه‌تر از این باشد، متن کامل از صفحهٔ مقاله خوانده می‌شود.
# اگر باز هم کوتاه بود، مقاله رد می‌شود تا مدل خلاصه‌ای از خودش نسازد.
MIN_CONTENT_CHARS = 1200
MAX_CONTENT_CHARS = 15000  # سقف متنی که برای مدل فرستاده می‌شود

# لینک‌هایی که مقاله نیستند
SKIP_LINK_PATTERNS = ("rss.app", "/podcast/", "/video/")
SKIP_EXACT_LINKS = {"https://www.theschooloflife.com/articles/"}

RLM = "‏"  # نشانهٔ راست‌به‌چپ؛ جهت خط را حتی وقتی با کلمهٔ انگلیسی شروع شود درست نگه می‌دارد
ZWNJ = "‌"
BULLET_EMOJIS = ["💡", "🎯", "🧠", "🌱", "🔍", "✨"]


# --- 2. MEMORY ---

def normalize_link(link):
    """لینک را یکدست می‌کند تا نسخه‌های مختلف یک مقاله (با utm یا # و اسلش) تکراری حساب شوند."""
    parts = urlsplit(link.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")]
    path = parts.path if parts.path.endswith("/") else parts.path + "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def get_posted_links():
    """لیست لینک‌های قبلاً پست شده را از حافظه می‌خواند"""
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return {normalize_link(line) for line in f if line.strip()}
    except FileNotFoundError:
        print("Memory file not found. Will create one.")
        return set()


def add_link_to_memory(link):
    """لینک جدید را به فایل حافظه اضافه می‌کند"""
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(link + "\n")
    print(f"Updated memory file with new link: {link}")


# --- 3. FETCHING ARTICLES ---

def html_to_text(content_html):
    soup = BeautifulSoup(content_html or "", "html.parser")
    for tag in soup(["script", "style", "figure", "iframe"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()


def entry_text(entry):
    content = entry.get("content") or [{}]
    return html_to_text(content[0].get("value") or entry.get("description", ""))


def fetch_page_text(http, url):
    """متن اصلی مقاله را از صفحهٔ وب می‌خواند (برای فیدهایی که فقط چکیده دارند)."""
    try:
        response = http.get(url)
        response.raise_for_status()
    except httpx.HTTPError as e:
        print(f"  Could not fetch page {url}: {e}")
        return ""
    soup = BeautifulSoup(response.text, "html.parser")
    root = soup.find("article") or soup.find("main") or soup
    return " ".join(p.get_text(" ", strip=True) for p in root.find_all("p"))


def is_skipped(link):
    return not link or link in SKIP_EXACT_LINKS or any(p in link for p in SKIP_LINK_PATTERNS)


def collect_from_feed(feed, source, posted_links, clean_title=None):
    articles = []
    for entry in feed.entries:
        link = (entry.get("link") or "").strip()
        title = (entry.get("title") or "").strip()
        if is_skipped(link) or not title or normalize_link(link) in posted_links:
            continue
        if clean_title:
            title = clean_title(title)
        articles.append({"title": title, "link": link, "content": entry_text(entry), "source": source})
    return articles


def get_all_unposted_articles(http, posted_links):
    """تمام مقالات پست نشده را از همه منابع (زنده و محلی) جمع‌آوری می‌کند"""
    print("Fetching articles from all sources...")
    articles = []

    # --- بخش اول: بررسی فیدهای زنده ---
    for source, url in LIVE_FEEDS.items():
        try:
            response = http.get(url)
            response.raise_for_status()
        except httpx.HTTPError as e:
            print(f"Could not fetch feed for {source}: {e}")
            continue
        found = collect_from_feed(feedparser.parse(response.content), source, posted_links)
        print(f"Live feed {source}: {len(found)} unposted")
        articles.extend(found)

    # --- بخش دوم: بررسی بانک مقالات محلی ---
    if os.path.exists(LOCAL_XML_FILE):
        with open(LOCAL_XML_FILE, "r", encoding="utf-8") as f:
            feed = feedparser.parse(f.read())
        found = collect_from_feed(
            feed, "The School of Life", posted_links,
            clean_title=lambda t: t.replace(" - The School of Life", "").strip(),
        )
        print(f"Local file {LOCAL_XML_FILE}: {len(found)} unposted")
        articles.extend(found)
    else:
        print(f"Warning: '{LOCAL_XML_FILE}' not found. Skipping local DB.")

    # یک مقاله ممکن است هم در فید زنده و هم در فایل محلی باشد
    unique = {normalize_link(a["link"]): a for a in reversed(articles)}
    return list(unique.values())


def pick_article(http, articles):
    """به‌صورت تصادفی مقاله‌ای انتخاب می‌کند که متن کافی برای خلاصه‌سازی داشته باشد."""
    random.shuffle(articles)
    for article in articles:
        if len(article["content"]) < MIN_CONTENT_CHARS:
            page_text = fetch_page_text(http, article["link"])
            if len(page_text) > len(article["content"]):
                article["content"] = page_text
        if len(article["content"]) >= MIN_CONTENT_CHARS:
            article["content"] = article["content"][:MAX_CONTENT_CHARS]
            return article
        print(f"  Skipping (not enough text): {article['title']}")
    return None


# --- 4. AI SUMMARY ---

SYSTEM_PROMPT = """
شما نویسنده‌ای عمیق و مسلط به فلسفه و روانشناسی هستید و برای یک کانال تلگرامی فارسی می‌نویسید.
وظیفه: یک مقالهٔ انگلیسی را به فارسی روان، گرم و مفهومی خلاصه کنید (در مجموع حدود ۲۰۰ تا ۲۸۰ کلمه).

خروجی را فقط به صورت یک JSON با این کلیدها برگردانید:
{
  "title": "ترجمهٔ روان و جذاب عنوان به فارسی، بدون گیومه",
  "hook": "یک یا دو جملهٔ کوتاه و گیرا که ایدهٔ اصلی را می‌گوید",
  "points": ["۳ تا ۵ نکتهٔ کلیدی؛ هر نکته حداکثر دو جملهٔ کوتاه"],
  "reflection": "یک جمله یا پرسش تأمل‌برانگیز برای پایان",
  "hashtags": ["دقیقاً ۵ هشتگ فارسی یک‌کلمه‌ای، بدون علامت #"]
}

قوانین مهم:
- به هیچ وجه از عبارات مقدمه‌چینی مانند «در این مقاله...»، «این مقاله به بررسی...»، «نویسنده بیان می‌کند...» یا «مقاله نشان می‌دهد...» استفاده نکنید. مستقیماً مفاهیم را توضیح دهید.
- فقط بر اساس متن مقاله بنویسید و چیزی از خودتان اضافه نکنید.
- از Markdown، ستاره، تگ HTML یا اموجی داخل متن‌ها استفاده نکنید (قالب‌بندی جداگانه انجام می‌شود).
- نام‌های خاص را به فارسی بنویسید و هیچ جمله‌ای را با کلمهٔ انگلیسی شروع نکنید.
- نیم‌فاصله را درست رعایت کنید (مثل «می‌شود»، «کتاب‌ها»).
"""


def parse_json_reply(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text)


def summarize(client, article):
    """خلاصه، عنوان و هشتگ‌ها را در یک درخواست می‌سازد."""
    print(f"Analyzing article: {article['title']}")
    user_message = f"Title: {article['title']}\n\nContent:\n{article['content']}"
    last_error = None
    for attempt in range(2):
        try:
            completion = client.chat.completions.create(
                model=MODEL_TO_USE,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                response_format={"type": "json_object"},
                max_tokens=1500,
                temperature=0.7,
            )
            data = parse_json_reply(completion.choices[0].message.content)
            if not data.get("points"):
                raise ValueError("model returned no points")
            print("✅ Summary generated successfully.")
            return data
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            print(f"Bad model output (attempt {attempt + 1}): {e}")
    raise RuntimeError(f"Could not get a valid summary: {last_error}")


# --- 5. TELEGRAM FORMATTING ---

def clean_persian(text):
    """متن را برای تلگرام تمیز می‌کند: حروف عربی، فاصله‌ها و نشانه‌های Markdown."""
    text = str(text or "")
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"^\s*(?:[-•*]|\d+[.)])\s+", "", text)  # بولت‌هایی که مدل خودش گذاشته
    text = text.replace("**", "").replace("__", "")
    return re.sub(r"[ \t]+", " ", text).strip()


def esc(text):
    return html.escape(clean_persian(text), quote=False)


def make_hashtag(tag):
    """هشتگ تلگرام فقط حرف، عدد و _ می‌پذیرد؛ نیم‌فاصله و فاصله هشتگ را می‌شکنند."""
    tag = clean_persian(tag).lstrip("#")
    tag = re.sub(rf"[\s{ZWNJ}\-]+", "_", tag)
    tag = re.sub(r"[^\w]", "", tag).strip("_")
    return f"#{tag}" if tag and not tag.isdigit() else ""


def telegram_length(text_html):
    """طول متن همان‌طور که تلگرام می‌شمارد: بعد از حذف تگ‌ها و به واحد UTF-16."""
    plain = html.unescape(re.sub(r"<[^>]+>", "", text_html))
    return len(plain.encode("utf-16-le")) // 2


def build_post(summary, article):
    title = esc(summary.get("title")) or html.escape(article["title"], quote=False)
    hook = esc(summary.get("hook"))
    reflection = esc(summary.get("reflection"))
    points = [esc(p) for p in summary.get("points", []) if clean_persian(p)][:5]

    hashtags = [make_hashtag(t) for t in summary.get("hashtags", [])]
    hashtags = list(dict.fromkeys(t for t in hashtags if t))[:5]
    if not hashtags:
        hashtags = [make_hashtag(article["source"])]

    link = html.escape(article["link"], quote=True)
    source = html.escape(article["source"], quote=False)

    def render(points):
        blocks = [f"{RLM}📌 <b>{title}</b>"]
        if hook:
            blocks.append(f"{RLM}<i>{hook}</i>")
        blocks.extend(f"{RLM}{BULLET_EMOJIS[i % len(BULLET_EMOJIS)]} {p}" for i, p in enumerate(points))
        if reflection:
            blocks.append(f"<blockquote>{RLM}🪞 {reflection}</blockquote>")
        blocks.append(f'{RLM}📖 <a href="{link}">متن کامل در {source}</a>')
        blocks.append(f"{RLM}{' '.join(hashtags)}\n{CHANNEL_HANDLE}")
        return "\n\n".join(blocks)

    post = render(points)
    # تلگرام پیام‌های بلندتر از ۴۰۹۶ کاراکتر را رد می‌کند؛ از نکته‌های آخر کم می‌کنیم
    while telegram_length(post) > MessageLimit.MAX_TEXT_LENGTH and len(points) > 1:
        points = points[:-1]
        post = render(points)
    return post


async def send_to_telegram(post, link):
    async with Bot(token=TELEGRAM_BOT_TOKEN) as bot:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=post,
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(url=link, prefer_large_media=True),
        )


# --- 6. EXECUTION ---

def main():
    missing = [name for name, value in (
        ("AVALAI_API_KEY", AVALAI_API_KEY),
        ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
        ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
    ) if not value and not (DRY_RUN and name != "AVALAI_API_KEY")]
    if missing:
        print(f"❌ Missing secrets: {', '.join(missing)}")
        return 1

    client = OpenAI(api_key=AVALAI_API_KEY, base_url=AVALAI_BASE_URL, timeout=90, max_retries=3)
    posted_links = get_posted_links()

    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT, follow_redirects=True) as http:
        articles = get_all_unposted_articles(http, posted_links)
        article = pick_article(http, articles)

    if article is None:
        print("No new (unposted) article with enough text found. Stopping.")
        return 0

    print(f"New article selected! Processing: {article['title']} ({article['link']})")
    post = build_post(summarize(client, article), article)

    if DRY_RUN:
        print("\n--- DRY RUN: post preview ---\n" + post)
        print(f"\n({telegram_length(post)} / {MessageLimit.MAX_TEXT_LENGTH} chars)")
        return 0

    asyncio.run(send_to_telegram(post, article["link"]))
    print("Post successfully sent.")
    # فقط بعد از ارسال موفق در حافظه ثبت می‌شود تا مقاله گم نشود
    add_link_to_memory(article["link"])
    print("\n--- AGENT RUN FINISHED ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
