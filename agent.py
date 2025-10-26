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

# این آدرس فید اصلی است، اما در تست زیر از آن استفاده نمی‌کنیم
RSS_FEED_URL = "https://rss.app/feed/tVpLudGvjlggDz0Z"
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
    # این تابع در حالت تست صدا زده نمی‌شود
    print(f"Fetching articles from {feed_url}...")
    cutoff_date = datetime.now() - timedelta(days=DAYS_TO_CHECK)
    
    try:
        feed = feedparser.parse(feed_url)
        if not feed.entries:
            print("No entries found in feed.")
            return None
        # ... (بقیه کد بدون تغییر)
    except Exception as e: 
        print(f"Could not fetch or parse feed. Error: {e}")
    print(f"No new articles found within the last {DAYS_TO_CHECK} days.")
    return None

def summarize_and_format(article):
    """مقاله را دریافت، به فارسی خلاصه و برای تلگرام فرمت‌بندی می‌کند."""
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

# --- 4. EXECUTION (MODIFIED FOR TEST) ---
def main():
    if client is None:
        print("Agent will not run. Check API Key.")
        return

    # --- H-A-R-D-C-O-D-E-D  T-E-S-T ---
    # ما تابع get_newest_article را صدا نمی‌زنیم و یک مقاله را دستی وارد می‌کنیم
    print("--- RUNNING IN TEST MODE ---")
    print("Bypassing feed fetch and using a hard-coded test article.")
    
    test_article = {
        "title": "Why Play Is a Serious Business",
        "link": "https://www.theschooloflife.com/blog/why-play-is-a-serious-business/",
        "content": """
        Play, in most people’s minds, is the opposite of work. To hear the word is to remember childhood afternoons... 
        Which is why it can be strange to consider a different argument. That we neglect play at our peril. That unbuttoning how we think of ‘serious work’ and incorporating more light-heartedness and experimentation into our routine can, in fact, boost the quality of our productive time.
        Play is immediate and fearless... Play is endlessly creative... Play can remind us of what makes work meaningful...
        The ideal position of play in life was first explored by the Ancient Greeks. Among all their gods, two mattered to them especially. The first was Apollo, god of reason and wisdom. He was concerned with patience, thoroughness, duty and logical thinking... But there was another important god... Dionysus. He was concerned with the imagination, impatience, chaos, emotion, instinct – and play.
        It’s important to keep in mind that these two sides of life, the frivolous and the imposing, the careful and the chaotic, can and should be embraced alongside one another.
        """
    }

    if test_article:
        report = summarize_and_format(test_article) # <--- تست تابع تحلیل
        if report:
            print("Test analysis complete. Sending to Telegram...")
            asyncio.run(send_to_telegram(report, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)) # <--- تست تابع تلگرام
        else:
            print("Test analysis failed.")
    else:
        print("Test article is empty.")
        
    print("\n--- AGENT TEST RUN FINISHED ---")

if __name__ == "__main__":
    main()
