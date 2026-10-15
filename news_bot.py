import sys
import os
import io
import re
import html
import json
import time
import difflib
import warnings
import requests
import feedparser
from dotenv import load_dotenv

# ==================== 0. .env تەڭشىكىنى يۈكلەش ====================
load_dotenv()

# ==================== 1. Encoding تەڭشىكى ====================
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.version_info[0] >= 3 and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

warnings.filterwarnings("ignore")

print("🟢 [Start] نادىر خەۋەر تاللاش ۋە تەرجىمە سىستېمىسى قوزغالدى...", flush=True)

# ==================== 2. ئاساسىي تەڭشەكلەر ====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "@uy1933news").strip()

HISTORY_FILE = "sent_history.json"
MAX_NEWS_PER_ROUND = 5
CHECK_INTERVAL_SECONDS = 3600

USE_TELEGRAM_PROXY = False
TELEGRAM_PROXIES = {
    "http": "http://127.0.0.1:7890",
    "https": "http://127.0.0.1:7890"
}

# ==================== 3. نادىر خەۋەر باھالاش سۆزلىرى ====================
PRIORITY_KEYWORDS = [
    "uyghur", "east turkestan", "شەرقىي تۈركىستان", "ئۇيغۇر",
    "syria", "turkey", "turkiye", "middle east", "ئوتتۇرا شەرق",
    "taiwan", "تەيۋەن", "us-china", "central asia", "gold"
]

GENERAL_KEYWORDS = [
    "usa", "china", "russia", "ukraine", "war", "conflict", "military",
    "sanctions", "geopolitics", "nato", "brics", "european union", "eu",
    "kazakhstan", "kyrgyzstan", "uzbekistan", "pakistan", "afghanistan",
    "india", "muslim", "economy", "taipei"
]

# ==================== 4. RSS خەۋەر مەنبەلىرى ====================
RSS_SOURCES = [
    {"name": "Radio Free Asia (Uyghur)", "url": "https://www.rfa.org/uyghur/rss2.xml"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "BBC World News", "url": "http://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "TRT World", "url": "https://www.trtworld.com/rss/world"},
    {"name": "Middle East Eye", "url": "https://www.middleeasteye.net/rss"},
    {"name": "Anadolu Agency (EN)", "url": "https://www.aa.com.tr/en/rss/default?cat=world"},
    {"name": "The Guardian", "url": "https://www.theguardian.com/world/rss"},
    {"name": "France 24", "url": "https://www.france24.com/en/rss"},
    {"name": "Deutsche Welle (DW)", "url": "https://rss.dw.com/rdf/rss-en-world"},
    {"name": "Focus Taiwan", "url": "https://focustaiwan.tw/rss/news.xml"},
    {"name": "Eurasianet", "url": "https://eurasianet.org/rss/feed"},
    {"name": "RFE/RL News", "url": "https://www.rferl.org/api/z-pqpiev-qpp"},
    {"name": "The Diplomat", "url": "https://thediplomat.com/feed/"},
    {"name": "Arab News", "url": "https://www.arabnews.com/rss.xml"}
]

# ==================== 5. ياردەمچى ئىقتىدارلار ====================

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("links", [])), data.get("titles", [])
        except Exception as e:
            print(f"⚠️ خاتىرە ئوقۇشتا خاتالىق: {e}", flush=True)
    return set(), []


def save_history(links, titles):
    try:
        data = {
            "links": list(links)[-400:],
            "titles": titles[-200:]
        }
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ خاتىرە ساقلاشتا خاتالىق: {e}", flush=True)


def clean_html(raw_text):
    if not raw_text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', raw_text)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def is_duplicate_news(title, sent_titles):
    for old_title in sent_titles:
        similarity = difflib.SequenceMatcher(None, title.lower(), old_title.lower()).ratio()
        if similarity > 0.65:
            return True
    return False


def calculate_news_score(title, summary, source_name):
    content = (title + " " + summary).lower()
    score = 0

    for kw in PRIORITY_KEYWORDS:
        if kw.lower() in content:
            score += 5

    for kw in GENERAL_KEYWORDS:
        if kw.lower() in content:
            score += 2

    if "Radio Free Asia" in source_name:
        score += 6

    if len(clean_html(summary)) > 120:
        score += 2

    return score


def fetch_rss_force(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        response = requests.get(url, headers=headers, timeout=12)
        if response.status_code == 200:
            return feedparser.parse(response.content)
    except Exception as e:
        print(f"⚠️ RSS ئۇلانمىدى ({url}): {e}", flush=True)
    return None


def extract_image_url(entry, article_link):
    if hasattr(entry, 'media_content') and entry.media_content:
        for media in entry.media_content:
            url = media.get('url', '')
            if url and url.startswith('http'):
                return url

    if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
        for thumb in entry.media_thumbnail:
            url = thumb.get('url', '')
            if url and url.startswith('http'):
                return url

    if hasattr(entry, 'enclosures') and entry.enclosures:
        for enc in entry.enclosures:
            url = enc.get('href', enc.get('url', ''))
            if url and ('image' in enc.get('type', '') or any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp'])):
                return url

    raw_html = getattr(entry, 'summary', '') + " " + getattr(entry, 'description', '')
    img_match = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', raw_html, re.IGNORECASE)
    if img_match:
        return img_match.group(1)

    if article_link:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            resp = requests.get(article_link, headers=headers, timeout=8)
            if resp.status_code == 200:
                og_match = re.search(
                    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](https?://[^"\']+)["\']',
                    resp.text, re.IGNORECASE
                )
                if not og_match:
                    og_match = re.search(
                        r'<meta[^>]+content=["\'](https?://[^"\']+)["\'][^>]+property=["\']og:image["\']',
                        resp.text, re.IGNORECASE
                    )
                if og_match:
                    return html.unescape(og_match.group(1))
        except Exception:
            pass

    return None


def translate_to_uyghur(text):
    if not text or not text.strip():
        return ""

    uyghur_chars = sum(1 for c in text if "\u0600" <= c <= "\u06FF")
    if uyghur_chars > len(text) * 0.4:
        return text

    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "auto", "tl": "ug", "dt": "t", "q": text}
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get(url, params=params, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            translated = "".join([part[0] for part in data[0] if part[0]])
            if translated:
                return translated
    except Exception as e:
        print(f"⚠️ تەرجىمىدە كىچىك مەسىلە: {e}", flush=True)

    return text


def smart_translate_and_summarize_free(title, summary):
    clean_title = clean_html(title)
    clean_sum = clean_html(summary)[:350] if summary else clean_title

    translated_title = translate_to_uyghur(clean_title)
    translated_summary = translate_to_uyghur(clean_sum)

    return (
        f"📌 ماۋزۇ: {translated_title}\n\n"
        f"📝 خۇلاسە: {translated_summary}"
    )


def send_telegram_news(message, image_url=None):
    if not TELEGRAM_BOT_TOKEN:
        print("❌ خاتالىق: TELEGRAM_BOT_TOKEN تېپىلمىدى!", flush=True)
        return False

    kwargs = {'timeout': 20}
    if USE_TELEGRAM_PROXY:
        kwargs['proxies'] = TELEGRAM_PROXIES

    if image_url:
        photo_api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "photo": image_url,
            "caption": message[:1024]
        }
        try:
            res = requests.post(photo_api, json=payload, **kwargs)
            if res.status_code == 200:
                return True
        except Exception:
            pass

    msg_api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": False
    }

    for attempt in range(3):
        try:
            res = requests.post(msg_api, json=payload, **kwargs)
            if res.status_code == 200:
                return True
            else:
                print(f"❌ Telegram API خاتالىقى ({res.status_code}): {res.text}", flush=True)
        except Exception:
            time.sleep(2)

    return False


# ==================== 6. نادىر خەۋەرلەرنى باھالاپ ئەۋەتىش ====================

def check_and_process_news():
    print(f"\n⏰ [{time.strftime('%Y-%m-%d %H:%M:%S')}] 1 سائەتلىك نادىر خەۋەر تاللاش باشلاندى...", flush=True)

    sent_links, sent_titles = load_history()
    candidates = []

    for source in RSS_SOURCES:
        feed = fetch_rss_force(source["url"])
        if not feed or not hasattr(feed, 'entries'):
            continue

        for entry in feed.entries:
            link = getattr(entry, 'link', '')
            title = getattr(entry, 'title', '')
            summary = getattr(entry, 'summary', getattr(entry, 'description', ''))

            if not link or not title:
                continue

            if link in sent_links:
                continue

            if is_duplicate_news(title, sent_titles):
                continue

            score = calculate_news_score(title, summary, source["name"])
            candidates.append({
                "score": score,
                "title": title,
                "summary": summary,
                "link": link,
                "source": source["name"],
                "entry": entry
            })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    selected_news = candidates[:MAX_NEWS_PER_ROUND]

    if not selected_news:
        print("📭 بۇ سائەتتە يېڭى نادىر خەۋەر تېپىلمىدى.", flush=True)
        return

    print(f"🔥 جەمئىي {len(selected_news)} تال نادىر خەۋەر تاللاپ تەرجىمە قىلىنىدۇ...", flush=True)

    success_count = 0
    for idx, item in enumerate(selected_news, 1):
        print(f"⚙️ [{idx}/{len(selected_news)}] تەرجىمە قىلىنىۋاتىدۇ: {item['title'][:50]}...", flush=True)
        
        formatted_msg = smart_translate_and_summarize_free(item['title'], item['summary'])
        final_message = f"{formatted_msg}\n\n🔗 تەپسىلاتى: {item['link']}\n🌐 مەنبە: {item['source']}"

        image_url = extract_image_url(item['entry'], item['link'])

        if send_telegram_news(final_message, image_url):
            print(f"✅ [نۆۋىتى {idx}] نادىر خەۋەر ئەۋەتىلدى!", flush=True)
            sent_links.add(item['link'])
            sent_titles.append(item['title'])
            success_count += 1
            time.sleep(3)
        else:
            print(f"❌ [نۆۋىتى {idx}] ئەۋەتىش مەغلۇپ بولды", flush=True)

    save_history(sent_links, sent_titles)
    print(f"🏁 بۇ سائەتلىك جەريان تاماملاندى. ئەۋەتىلگىنى: {success_count} دانە.", flush=True)


if __name__ == "__main__":
    check_and_process_news()
