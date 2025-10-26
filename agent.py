import os
import feedparser
import telegram
import asyncio
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from openai import OpenAI

# --- 1. CONFIGURATION ---
AVALAI_API_KEY = os.environ.get("AVALAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") 
AVALAI_BASE_URL = "https://api.avalai.ir/v1"
MODEL_TO_USE = "gpt-4o-mini" 

# --- !!!!!!!!!!!!!!!!!!!!!!!!!!!!! ---
# --- این خط را با فید RSS سفارشی خود جایگزین کنید ---
RSS_FEED_URL = "https://rss.app/feed/tVpLudGvjlggDz0Z"
# --- !!!!!!!!!!!!!!!!!!!!!!!!!!!!! ---

DAYS_TO_CHECK = 2 

# --- 2. INITIALIZE THE AI CLIENT ---
client = None
if AVALAI_API_KEY:
    try:
        client = OpenAI(
            api_key=AVALAI_API_KEY,
            base_url=AVALAI_BASE_URL,
        )
        print("✅ AvalAI client configured successfully.")
    except Exception as e:
        print(f"❌ Critical error during client initialization: {e}")
else:
    print("❌ AVALAI_API_KEY secret is not set.")

# --- 3. FUNCTIONS ---

def get_newest_article(feed_url):
    print(f"Fetching articles from {feed_url}...")
    cutoff_date = datetime.now() - timedelta(days=DAYS_TO_CHECK)

    try:
        feed = feedparser.parse(feed_url)
        if not feed.entries:
            print("No entries found in feed.")
            return None

        for entry in feed.entries:
            published_time_struct = getattr(entry, 'published_parsed', None)
            if published_time_struct:
                 published_time = datetime(*published_time_struct[:6])
                 if published_time >= cutoff_date:
                    print(f"Found new article: {entry.title}")

                    content_html = entry.get('content', [{}])[0].get('value', '')
                    if not content_html:
                        content_html = getattr(entry, 'description', '')

                    summary_text = BeautifulSoup(content_html, 'html.parser').get_text()

                    article = {
                        "title": entry.title,
                        "link": entry.link,
                        "content": summary_text
                    }
                    return article 
    except Exception as e: 
        print(f"Could not fetch or parse feed. Error: {e}")

    print(f"No new articles found within the last {DAYS_TO_CHECK} days.")
    return None

def summarize_and_format(article):
    if client is None: 
        return "AI client is not available."

    print(f"Analyzing article: {article['title']}")

    system_message = "شما یک نویسنده و متفکر عمیق مسلط به فلسفه و روانشناسی هستید. وظیفه شما دریافت یک مقاله انگلیسی از سایت The School of Life و خلاصه‌سازی عمیق و مفهومی آن به زبان فارسی است. خلاصه باید روان، جذاب و فلسفی باشد و مفاهیم اصلی مقاله را به خوبی منتقل کند. از نوشتن هرگونه متن اضافه یا مقدمه‌چینی خودداری کنید."
    user_message = f"Please summarize this article in fluid, engaging Persian:\n\nTitle: {article['title']}\n\nContent:\n{article['content']}"

    try:
        completion = client.chat.completions.create(
            model=MODEL_TO_USE,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            max_tokens=2048, 
            temperature=0.7,
        )
        persian_summary = completion.choices[0].message.content.strip()

        final_post = (
            f"<b>{article['title']}</b>\n\n"
            f"{persian_summary}\n\n"
            f"<i>منبع: The School of Life</i>\n"
            f"<a href='{article['link']}'>ادامه مطلب</a>"
        )
        return final_post

    except Exception as e:
        print(f"Could not analyze article. Error: {e}")
        return None

async def send_to_telegram(report, token, chat_id):
    if not token or not chat_id: 
        print("Telegram secrets not found.")
        return
    print("Sending post to Telegram...")
    try:
        bot = telegram.Bot(token=token)
        await bot.send_message(
            chat_id=chat_id, 
            text=report, 
            parse_mode='HTML',
            disable_web_page_preview=True
        )
        print("Post successfully sent.")
    except Exception as e: 
        print(f"Failed to send post. Error: {e}")

# --- 4. EXECUTION ---
def main():
    if client is None:
        print("Agent will not run.")
        return

    article = get_newest_article(RSS_FEED_URL)

    if article:
        report = summarize_and_format(article)
        if report:
            asyncio.run(send_to_telegram(report, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID))
    else:
        print("No new article to post today.")

    print("\n--- AGENT RUN FINISHED ---")

if __name__ == "__main__":
    main()
