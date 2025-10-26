import os
import feedparser
import telegram
import asyncio
import time
import random
from bs4 import BeautifulSoup
from openai import OpenAI

# --- 1. CONFIGURATION ---
AVALAI_API_KEY = os.environ.get("AVALAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
AVALAI_BASE_URL = "https://api.avalai.ir/v1"
MODEL_TO_USE = "gpt-4o-mini" 

LOCAL_XML_FILE = "content.xml"
MEMORY_FILE = "_posted_articles.txt"

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
    try:
        with open(MEMORY_FILE, 'r') as f:
            return set(line.strip() for line in f.readlines() if line.strip())
    except FileNotFoundError:
        print("Memory file not found. Will create one.")
        return set()

def add_link_to_memory(link):
    try:
        with open(MEMORY_FILE, 'a') as f:
            f.write(link + '\n')
        print(f"Updated memory file with new link: {link}")
    except Exception as e:
        print(f"Error writing to memory file: {e}")

def get_unposted_article(xml_file, posted_links):
    print(f"Fetching articles from local file: {xml_file}...")
    try:
        feed = feedparser.parse(xml_file)
        if not feed.entries:
            print("No entries found in local XML file.")
            return None
            
        unposted_articles = []
        for entry in feed.entries:
            if entry.link not in posted_links:
                unposted_articles.append(entry)
        
        if not unposted_articles:
            print("All articles from the database have been posted.")
            return None
            
        chosen_entry = random.choice(unposted_articles)
        print(f"New article selected to post: {chosen_entry.title}")
        
        content_html = chosen_entry.get('content', [{}])[0].get('value', '')
        if not content_html:
            content_html = getattr(chosen_entry, 'description', '')
        
        summary_text = BeautifulSoup(content_html, 'html.parser').get_text()
        
        article = {
            "title": chosen_entry.title,
            "link": chosen_entry.link,
            "content": summary_text
        }
        return article
        
    except Exception as e: 
        print(f"Could not parse local XML file. Error: {e}")
        return None

def summarize_and_format(article):
    if client is None: return "AI client is not available.", None
    print(f"Analyzing article: {article['title']}")
    
    # --- STEP 1: Generate a longer, detailed, emoji-bulleted summary ---
    # --- FIX: Prompt updated to use emojis (e.g., 💡, 🎯, 🚀) instead of markdown '*' ---
    system_message_summary = "شما یک نویسنده و متفکر عمیق مسلط به فلسفه و روانشناسی هستید. وظیفه شما دریافت یک مقاله انگلیسی از سایت The School of Life و نوشتن یک خلاصه تحلیلی عمیق و مفهومی (حدود ۲۵۰ تا ۳۰۰ کلمه) به زبان فارسی است. خلاصه باید روان و جذاب باشد. مفاهیم اصلی را با استفاده از اموجی‌های مناسب (مانند 💡, 🎯, 🚀, 🧠) به جای بولت پوینت، دسته‌بندی کنید تا خوانایی بالا برود. مستقیماً خلاصه را شروع کنید و هیچ مقدمه یا توضیحی درباره کاری که انجام می‌دهید ننویسید."
    user_message_summary = f"Please summarize this article in a detailed, 250-300 word, fluid, and engaging Persian summary, using emojis for key concepts:\n\nTitle: {article['title']}\n\nContent:\n{article['content']}"
    
    persian_summary = ""
    try:
        completion_summary = client.chat.completions.create(model=MODEL_TO_USE, messages=[{"role": "system", "content": system_message_summary}, {"role": "user", "content": user_message_summary}], max_tokens=3000, temperature=0.7)
        persian_summary = completion_summary.choices[0].message.content.strip()
        print("✅ Summary generated successfully.")
    except Exception as e:
        print(f"Could not analyze article. Error: {e}")
        return None, None

    # --- STEP 2: Translate the Title (No change needed) ---
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

    # --- STEP 3: Generate Hashtags (No change needed) ---
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
        hashtags_string = "#خلاصه" 

    # --- STEP 4: Assemble Final Post (Using HTML bold tags) ---
    # --- FIX: Use <b> for bold, not ** ---
    final_post = (
        f"<b>{persian_title}</b>\n\n" 
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
        await bot.send_message(
            chat_id=chat_id, 
            text=report, 
            parse_mode='HTML', # --- HTML mode is correct ---
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
    new_article = get_unposted_article(LOCAL_XML_FILE, posted_links)
    
    if new_article is None:
        print("No new (unposted) article found in local database. Stopping.")
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
