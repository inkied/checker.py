import os
import random
import string
import threading
import queue
import requests
from time import sleep

# Env vars from Railway
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
WEBSHARE_API_KEY = os.getenv("WEBSHARE_KEY")

if not all([TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, WEBSHARE_API_KEY]):
    print("[FATAL] Missing env variables.")
    exit(1)

# Username generation
vowels = "aeiou"
consonants = ''.join(set(string.ascii_lowercase) - set(vowels))

def generate_usernames(limit=5000):
    usernames = set()
    while len(usernames) < limit:
        pattern = random.choice(['CVCV', 'VCVC', 'repeat'])
        if pattern == 'repeat':
            ch = random.choice(consonants)
            usernames.add(ch * 4)
        else:
            uname = ''
            for p in pattern:
                uname += random.choice(consonants if p == 'C' else vowels)
            usernames.add(uname)
    return list(usernames)

# Fetch proxies from Webshare (HTTP only)
def fetch_proxies():
    print("[INFO] Fetching proxies...")
    url = "https://proxy.webshare.io/api/v2/proxy/list/"
    headers = {"Authorization": f"Token {WEBSHARE_API_KEY}"}
    params = {"mode": "direct", "page": 1, "page_size": 100}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        proxies = []
        for p in data.get("results", []):
            address = p.get("proxy_address")
            port = p.get("ports", {}).get("http")
            if address and port:
                proxies.append(f"http://{address}:{port}")
        print(f"[INFO] Fetched {len(proxies)} proxies.")
        return proxies
    except Exception as e:
        print(f"[ERROR] Proxy fetch failed: {e}")
        return []

# Telegram message sender
def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        requests.post(url, data=data, timeout=10)
    except:
        pass

# Worker to check username availability
def worker(queue, proxies, found_lock, found_list):
    session = requests.Session()
    while True:
        try:
            username = queue.get(timeout=5)
        except:
            break
        proxy = random.choice(proxies) if proxies else None
        proxies_dict = {"http": proxy, "https": proxy} if proxy else None
        url = f"https://www.tiktok.com/@{username}"
        try:
            resp = session.get(url, proxies=proxies_dict, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 404:
                msg = f"🔥 Available TikTok username: {username}"
                print(msg)
                send_telegram_message(msg)
                with found_lock:
                    found_list.append(username)
            # No print on taken or errors
        except:
            # Silently skip errors
            pass
        sleep(random.uniform(0.3, 0.7))
        queue.task_done()

def main():
    usernames = generate_usernames(5000)
    proxies = fetch_proxies()
    if not proxies:
        print("[WARN] No proxies fetched, continuing without proxies.")
    q = queue.Queue()
    for uname in usernames:
        q.put(uname)

    found = []
    found_lock = threading.Lock()
    thread_count = 20

    threads = []
    for _ in range(thread_count):
        t = threading.Thread(target=worker, args=(q, proxies, found_lock, found))
        t.daemon = True
        t.start()
        threads.append(t)

    q.join()  # Wait for queue to empty

    print(f"[INFO] Done! {len(found)} available usernames found.")
    if found:
        with open("available.txt", "w") as f:
            f.write("\n".join(found))
        print("[INFO] Saved available usernames to available.txt")

if __name__ == "__main__":
    main()
