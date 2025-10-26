import os
import feedparser
import telegram
import asyncio
import time
import random
from bs4 import BeautifulSoup
from openai import OpenAI
from datetime import datetime, timedelta

# --- 1. CONFIGURATION ---
AVALAI_API_KEY = os.environ.get("AVALAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
AVALAI_BASE_URL = "https://api.avalai.ir/v1"
MODEL_TO_USE = "gpt-4o-mini" 

# --- FINAL, VERIFIED RSS FEEDS ---
JOURNAL_FEEDS = {
    "The School of Life": "https://www.theschooloflife.com/feed/",
    "Aeon": "https://aeon.co/feed.rss",
    "The Marginalian": "https://www.themarginalian.org/feed/",
    "Nautilus": "https://nautil.us/feed/",
    "Big Think": "https://bigthink.com/feed/",
    "Scientific American Mind & Brain": "http://rss.sciam.com/sciam/mind-and-brain",
    "Quanta Magazine": "https://api.quantamagazine.org/feed/",
    "The Atlantic - Ideas": "https://www.theatlantic.com/feed/channel/ideas/"
}
DAYS_TO_CHECK = 30 # فقط مقالات ۲۴ ساعت گذشته
MEMORY_FILE = "_posted_articles.txt" # فایل حافظه

# --- 2. INITIALIZE THE AI CLIENT ---
client = None
if AVALAI_API_KEY:
    try:
        client = OpenAI(api_key=AVALAI_API_KEY, base_url=AVALAI_BASE_URL)
        print("✅ AvalAI client configured successfully.")
    except Exception as e:
        print(f"❌ Critical error during client initialization: {e}")
else:
    print("❌ AVALAI_API_KEY secret is not set.")

# --- 3. FUNCTIONS ---

def get_posted_links():
    """لیست لینک‌های قبلاً پست شده را از حافظه می‌خواند"""
    try:
        with open(MEMORY_FILE, 'r') as f:
            return set(line.strip() for line in f.readlines() if line.strip())
    except FileNotFoundError:
        print("Memory file not found. Will create one.")
        return set()

def add_link_to_memory(link):
    """لینک جدید را به فایل حافظه اضافه می‌کند"""
    try:
        with open(MEMORY_FILE, 'a') as f:
            f.write(link + '\n')
        print(f"Updated memory file with new link: {link}")
    except Exception as e:
        print(f"Error writing to memory file: {e}")

def get_unposted_article(feeds, posted_links):
    """جدیدترین مقالاتی که پست نشده‌اند را از همه فیدها پیدا می‌کند"""
    print("Fetching articles from all live feeds...")
    cutoff_date = datetime.now() - timedelta(days=DAYS_TO_CHECK)
    new_articles_found = []
    
    for journal, url in feeds.items():
        print(f"Checking feed: {journal}")
        try:
            feed = feedparser.parse(url)
            if not feed.entries:
                print(f"No entries found for {journal}.")
                continue
                
            for entry in feed.entries:
                link = entry.link
                if link in posted_links:
                    continue # این مقاله قبلاً پست شده است

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
                            "title": entry.title.strip(),
                            "link": link,
                            "content": summary_text,
                            "source": journal # نام منبع
                        }
                        new_articles_found.append(article)
                        break 
        except Exception as e: 
            print(f"Could not fetch or parse feed for {journal}. Error: {e}")
    
    if not new_articles_found:
        print("No new (unposted) articles found in any feed.")
        return None
        
    chosen_article = random.choice(new_articles_found)
    return chosen_article

def summarize_and_format(article):
    """مقاله را دریافت، خلاصه کرده، هشتگ می‌سازد و برای تلگرام فرمت‌بندی می‌کند."""
    if client is None: return "AI client is not available.", None
    print(f"Analyzing article: {article['title']}")
    
    # --- STEP 1: Generate Summary ---
    system_message_summary = "شما یک نویسنده و متفکر عمیق مسلط به فلسفه و روانشناسی هستید. وظیفه شما دریافت یک مقاله انگلیسی و نوشتن یک خلاصه تحلیلی عمیق و مفهومی (حدود ۲۵۰ تا ۳۰۰ کلمه) به زبان فارسی است. خلاصه باید روان، جذاب و فلسفی باشد. مفاهیم اصلی را با استفاده از اموجی‌های مناسب (مانند 💡, 🎯, 🧠) به جای بولت پوینت، دسته‌بندی کنید تا خوانایی بالا برود. مستقیماً خلاصه را شروع کنید و هیچ مقدمه یا توضیحی درباره کاری که انجام می‌دهید ننویسید."
    user_message_summary = f"Please summarize this article in a detailed, 250-300 word, fluid, and engaging Persian summary, using emojis for key concepts:\n\nTitle: {article['title']}\n\nContent:\n{article['content']}"
    
    persian_summary = ""
    try:
        completion_summary = client.chat.completions.create(model=MODEL_TO_USE, messages=[{"role": "system", "content": system_message_summary}, {"role": "user", "content": user_message_summary}], max_tokens=3000, temperature=0.7)
        persian_summary = completion_summary.choices[0].message.content.strip()
        print("✅ Summary generated successfully.")
    except Exception as e:
        print(f"Could not analyze article. Error: {e}")
        return None, None

    # --- STEP 2: Translate Title ---
    print("Waiting for 5 seconds...")
    time.sleep(5)
    system_message_title = "Translate the following English title to Persian. Only return the translated text, nothing else."
    user_message_title = article['title']
    persian_title = article['title'] 
    try:
        completion_title = client.chat.completions.create(model=MODEL_TO_USE, messages=[{"role": "system", "content": system_message_title}, {"role": "user", "content": user_message_title}], max_tokens=100, temperature=0.1)
        persian_title = completion_title.choices[0].message.content.strip()
        print(f"✅ Title translated successfully: {persian_title}")
    except Exception as e:
        print(f"Could not translate title. Error: {e}")

    # --- STEP 3: Generate Hashtags ---
    print("Waiting for 5 seconds...")
    time.sleep(5)
    system_message_hashtags = "You are a metadata specialist. Read the following text and generate exactly 5 relevant, single-word hashtags in Persian. Do not include the '#' symbol. Separate them with commas."
    user_message_hashtags = f"Text:\n{persian_summary}"
    hashtags_string = ""
    try:
        completion_tags = client.chat.completions.create(model=MODEL_TO_USE, messages=[{"role": "system", "content": system_message_hashtags}, {"role": "user", "content": user_message_hashtags}], max_tokens=100, temperature=0.2)
        tags = completion_tags.choices[0].message.content.strip()
        hashtags_string = " ".join([f"#{tag.strip().replace(' ', '_')}" for tag in tags.split(',')]) 
        print(f"✅ Hashtags generated: {hashtags_string}")
    except Exception as e:
        print(f"Could not generate hashtags. Error: {e}")
        hashtags_string = f"#{article['source'].lower().replace(' ', '')}" 

    # --- STEP 4: Assemble Final Post ---
    final_post = (
        f"<b>{persian_title}</b>\n\n" 
        f"{persian_summary}\n\n"
        f"{hashtags_string}\n\n"
        f"<i>منبع: {article['source']}</i>\n"
        f"<a href='{article['link']}'>ادامه مطلب</a>\n"
        f"@momento_lab 💡"
    )
    return final_post, article['link']
        
async def send_to_telegram(report, token, chat_id):
    if not token or not chat_id: print("Telegram secrets not found."); return
    print("Sending post to Telegram...")
    try:
        bot = telegram.Bot(token=token)
        await bot.send_message(
            chat_id=chat_id, 
            text=report, 
            parse_mode='HTML',
            disable_web_page_preview=False
        )
        print("Post successfully sent.")
    except Exception as e: print(f"Failed to send post. Error: {e}")

# --- 5. EXECUTION (with memory logic) ---
def main():
    if client is None:
        print("Agent will not run. Check API Key.")
        return

    posted_links = get_posted_links()
    new_article = get_unposted_article(JOURNAL_FEEDS, posted_links)
    
    if new_article is None:
        print("No new (unposted) articles found in any feed. Stopping.")
        print("\n--- AGENT RUN FINISHED ---")
        return
        
    print(f"New article selected! Processing: {new_article['title']}")
    report, new_link = summarize_and_format(new_article)
    
    if report:
        asyncio.run(send_to_telegram(report, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID))
        add_link_to_memory(new_link) 
    else:
        print("Failed to generate report.")
        
    print("\n--- AGENT RUN FINISHED ---")

if __name__ == "__main__":
    main()
