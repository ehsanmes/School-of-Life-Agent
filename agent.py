import os
import feedparser
import telegram
import asyncio
import time
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from openai import OpenAI

# --- 1. CONFIGURATION ---
AVALAI_API_KEY = os.environ.get("AVALAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
AVALAI_BASE_URL = "https://api.avalai.ir/v1"
MODEL_TO_USE = "gpt-4o-mini" 

RSS_FEED_URL = "https://rss.app/feed/tVpLudGvjlggDz0Z"
MEMORY_FILE = "_last_processed_link.txt" 

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

def get_last_processed_link():
    """لینک ذخیره شده در فایل حافظه را می‌خواند"""
    try:
        with open(MEMORY_FILE, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        print("Memory file not found. Will create one.")
        return None

def set_last_processed_link(link):
    """لینک جدید را در فایل حافظه می‌نویسد"""
    try:
        with open(MEMORY_FILE, 'w') as f:
            f.write(link)
        print(f"Updated memory file with new link: {link}")
    except Exception as e:
        print(f"Error writing to memory file: {e}")

def get_newest_article(feed_url):
    """جدیدترین مقاله را پیدا می‌کند"""
    print(f"Fetching articles from {feed_url}...")
    try:
        feed = feedparser.parse(feed_url)
        if not feed.entries:
            print("No entries found in feed.")
            return None
            
        latest_article_entry = feed.entries[0] 
        
        content_html = latest_article_entry.get('content', [{}])[0].get('value', '')
        if not content_html:
            content_html = getattr(latest_article_entry, 'description', '')
        
        summary_text = BeautifulSoup(content_html, 'html.parser').get_text()
        
        article = {
            "title": latest_article_entry.title,
            "link": latest_article_entry.link,
            "content": summary_text
        }
        return article
    except Exception as e: 
        print(f"Could not fetch or parse feed. Error: {e}")
        return None

def summarize_and_format(article):
    """مقاله را دریافت، خلاصه کرده، هشتگ می‌سازد و برای تلگرام فرمت‌بندی می‌کند."""
    if client is None: 
        return "AI client is not available.", None

    print(f"Analyzing article: {article['title']}")
    
    # --- STEP 1: Generate a longer, more detailed summary ---
    # --- FIX 2 & 3: Prompt for a longer summary, directly starting the text ---
    system_message_summary = "شما یک نویسنده و متفکر عمیق مسلط به فلسفه و روانشناسی هستید. وظیفه شما دریافت یک مقاله انگلیسی از سایت The School of Life و نوشتن یک خلاصه تحلیلی عمیق و مفهومی (حدود ۲۵۰ تا ۳۰۰ کلمه) به زبان فارسی است. خلاصه باید روان، جذاب و فلسفی باشد. مستقیماً خلاصه را شروع کنید و هیچ مقدمه یا توضیحی درباره کاری که انجام می‌دهید ننویسید."
    user_message_summary = f"Please summarize this article in a detailed, 250-300 word, fluid, and engaging Persian summary:\n\nTitle: {article['title']}\n\nContent:\n{article['content']}"
    
    persian_summary = ""
    try:
        completion_summary = client.chat.completions.create(
            model=MODEL_TO_USE,
            messages=[
                {"role": "system", "content": system_message_summary},
                {"role": "user", "content": user_message_summary},
            ],
            max_tokens=3000, # Increased tokens
            temperature=0.7,
        )
        persian_summary = completion_summary.choices[0].message.content.strip()
        print("✅ Summary generated successfully.")
    except Exception as e:
        print(f"Could not analyze article. Error: {e}")
        return None, None

    # --- STEP 2: Translate the Title ---
    # --- FIX 1: Generate Persian Title ---
    print("Waiting for 5 seconds...")
    time.sleep(5)
    
    system_message_title = "Translate the following English title to Persian. Only return the translated text, nothing else."
    user_message_title = article['title']
    persian_title = article['title'] # Fallback to English title
    
    try:
        completion_title = client.chat.completions.create(
            model=MODEL_TO_USE,
            messages=[
                {"role": "system", "content": system_message_title},
                {"role": "user", "content": user_message_title},
            ],
            max_tokens=100,
            temperature=0.1,
        )
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
        completion_tags = client.chat.completions.create(
            model=MODEL_TO_USE,
            messages=[
                {"role": "system", "content": system_message_hashtags},
                {"role": "user", "content": user_message_hashtags},
            ],
            max_tokens=100,
            temperature=0.2,
        )
        tags = completion_tags.choices[0].message.content.strip()
        hashtags_string = " ".join([f"#{tag.strip().replace(' ', '_')}" for tag in tags.split(',')]) 
        print(f"✅ Hashtags generated: {hashtags_string}")
    except Exception as e:
        print(f"Could not generate hashtags. Error: {e}")
        hashtags_string = "#خلاصه" 

    # --- STEP 4: Assemble Final Post (All fixes applied) ---
    final_post = (
        f"<b>{persian_title}</b>\n\n" # FIX 1: Use Persian Title
        f"{persian_summary}\n\n"
        f"{hashtags_string}\n\n"
        f"<a href='{article['link']}'>منبع</a>\n" # FIX 2: Hyperlinked source
        f"@momento_lab 💡" # FIX 4: Your signature
    )
    return final_post, article['link']
        
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
            disable_web_page_preview=False # --- FIX 4: Enabled link preview ---
        )
        print("Post successfully sent.")
    except Exception as e: 
        print(f"Failed to send post. Error: {e}")

# --- 5. EXECUTION (with memory logic) ---
def main():
    if client is None:
        print("Agent will not run. Check API Key.")
        return

    last_link = get_last_processed_link()
    new_article = get_newest_article(RSS_FEED_URL)
    
    if new_article is None:
        print("No articles found in feed. Stopping.")
        print("\n--- AGENT RUN FINISHED ---")
        return

    if new_article['link'] == last_link:
        print("Article is the same as last run. No new article found. Stopping.")
        print("\n--- AGENT RUN FINISHED ---")
        return
        
    print(f"New article found! Processing: {new_article['title']}")
    report, new_link = summarize_and_format(new_article)
    
    if report:
        asyncio.run(send_to_telegram(report, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID))
        set_last_processed_link(new_link) 
    else:
        print("Failed to generate report.")
        
    print("\n--- AGENT RUN FINISHED ---")

if __name__ == "__main__":
    main()
