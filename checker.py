import requests
import threading
import random
import string
import os
from queue import Queue
from time import sleep

telegram_token = os.getenv("TELEGRAM_TOKEN")
telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    data = {"chat_id": telegram_chat_id, "text": text}
    try:
        requests.post(url, data=data, timeout=10)
    except:
        pass

def generate_usernames(limit=5000):
    vowels = "aeiou"
    consonants = ''.join(set(string.ascii_lowercase) - set(vowels))
    usernames = set()
    while len(usernames) < limit:
        pattern = random.choice(['CVCV', 'VCVC', 'repeat'])
        if pattern == 'repeat':
            ch = random.choice(consonants)
            usernames.add(ch*4)
        else:
            uname = ''.join(random.choice(consonants if p == 'C' else vowels) for p in pattern)
            usernames.add(uname)
    return list(usernames)

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
            with session.get(url, proxies=proxies_dict, timeout=10, headers={"User-Agent": "Mozilla/5.0"}) as resp:
                if resp.status_code == 404:
                    msg = f"🔥 Available TikTok username: {username}"
                    print(msg)
                    send_telegram_message(msg)
                    with found_lock:
                        found_list.append(username)
                # Don't print anything if taken or error
        except:
            pass
        sleep(random.uniform(0.3, 0.7))
        queue.task_done()

def main():
    proxies = []  # Add your proxies here or leave empty
    usernames = generate_usernames(5000)
    q = Queue()
    for u in usernames:
        q.put(u)

    found = []
    found_lock = threading.Lock()
    threads = []
    for _ in range(20):  # 20 threads, adjust as needed
        t = threading.Thread(target=worker, args=(q, proxies, found_lock, found))
        t.daemon = True
        t.start()
        threads.append(t)

    q.join()
    print(f"Finished! Available usernames: {len(found)}")

if __name__ == "__main__":
    main()
