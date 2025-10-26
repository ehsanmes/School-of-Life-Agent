import os
import feedparser
import telegram
import asyncio
import time
import requests # <--- کتابخانه requests را برای اسکرپینگ اضافه می‌کنیم
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
# --- آدرس مستقیم صفحه مقالات ---
ARTICLES_PAGE_URL = "https://www.theschooloflife.com/articles/"
# --- !!!!!!!!!!!!!!!!!!!!!!!!!!!!! ---

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

def get_newest_article_from_webpage(url):
    """مستقیماً صفحه وب را اسکرپ می‌کند تا جدیدترین مقاله را پیدا کند"""
    print(f"Scraping webpage: {url}...")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status() # بررسی خطا
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # بر اساس ساختار سایت The School of Life، مقالات در تگ <article> هستند
        latest_article_element = soup.find('article')
        
        if not latest_article_element:
            print("No <article> tag found on the page.")
            return None

        # پیدا کردن لینک و عنوان
        link_tag = latest_article_element.find('a', href=True)
        title_tag = latest_article_element.find('h3') # یا تگ عنوان مناسب دیگر
        
        if not link_tag or not title_tag:
            print("Could not find link or title tag within the article element.")
            return None

        article_link = link_tag['href']
        article_title = title_tag.get_text().strip()
        
        # حالا به صفحه خود مقاله می‌رویم تا متن کامل را بگیریم
        print(f"Found latest article: {article_title}. Fetching content...")
        article_response = requests.get(article_link, headers=headers, timeout=15)
        article_response.raise_for_status()
        
        article_soup = BeautifulSoup(article_response.content, 'html.parser')
        
        # پیدا کردن بخش محتوای اصلی مقاله
        content_element = article_soup.find('div', class_='entry-content') # کلاس معمول برای محتوای پست
        if not content_element:
            content_element = article_soup.find('article') # بازگشت به تگ مقاله
            
        if not content_element:
            print("Could not find main content element on article page.")
            return None

        # استخراج متن تمیز
        article_text = content_element.get_text(separator='\n', strip=True)
        
        article = {
            "title": article_title,
            "link": article_link,
            "content": article_text
        }
        return article
        
    except Exception as e: 
        print(f"Could not scrape webpage. Error: {e}")
        return None

def summarize_and_format(article):
    """مقاله را دریافت، خلاصه کرده، هشتگ می‌سازد و برای تلگرام فرمت‌بندی می‌کند."""
    if client is None: return "AI client is not available.", None
    print(f"Analyzing article: {article['title']}")
    
    system_message_summary = "شما یک نویسنده و متفکر عمیق مسلط به فلسفه و روانشناسی هستید. وظیفه شما دریافت یک مقاله انگلیسی از سایت The School of Life و نوشتن یک خلاصه تحلیلی عمیق و مفهومی (حدود ۱۵۰ تا ۲۰۰ کلمه) به زبان فارسی است. خلاصه باید روان، جذاب و فلسفی باشد و مفاهیم اصلی مقاله را به خوبی منتقل کند. از مقدمه‌چینی خودداری کنید و مستقیماً به سراغ تحلیل بروید."
    user_message_summary = f"Please summarize this article in a detailed, fluid, and engaging Persian summary:\n\nTitle: {article['title']}\n\nContent:\n{article['content']}"
    
    persian_summary = ""
    try:
        completion_summary = client.chat.completions.create(model=MODEL_TO_USE, messages=[{"role": "system", "content": system_message_summary}, {"role": "user", "content": user_message_summary}], max_tokens=2048, temperature=0.7)
        persian_summary = completion_summary.choices[0].message.content.strip()
        print("✅ Summary generated successfully.")
    except Exception as e:
        print(f"Could not analyze article. Error: {e}")
        return None, None

    print("Waiting for 5 seconds before generating hashtags...")
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
        hashtags_string = "#خلاصه" 

    final_post = (
        f"<b>{article['title']}</b>\n\n"
        f"{persian_summary}\n\n"
        f"{hashtags_string}\n\n"
        f"<a href='{article['link']}'>منبع</a>\n"
        f"@momento_lab 💡"
    )
    return final_post, article['link'] 
        
async def send_to_telegram(report, token, chat_id):
    if not token or not chat_id: print("Telegram secrets not found."); return
    print("Sending post to Telegram...")
    try:
        bot = telegram.Bot(token=token)
        await bot.send_message(chat_id=chat_id, text=report, parse_mode='HTML', disable_web_page_preview=True)
        print("Post successfully sent.")
    except Exception as e: print(f"Failed to send post. Error: {e}")

# --- 4. EXECUTION (with new scraping logic) ---
def main():
    if client is None:
        print("Agent will not run. Check API Key.")
        return

    last_link = get_last_processed_link()
    new_article = get_newest_article_from_webpage(ARTICLES_PAGE_URL) # <--- استفاده از تابع جدید
    
    if new_article is None:
        print("No articles found on webpage. Stopping.")
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
        set_last_processed_link(new_link) # ذخیره لینک جدید در حافظه
    else:
        print("Failed to generate report.")
        
    print("\n--- AGENT RUN FINISHED ---")

if __name__ == "__main__":
    main()
