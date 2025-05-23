# checker.py
import os, sys, asyncio, aiohttp, random, string, time
from collections import deque, defaultdict
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# ────────────────── ENV & BASIC VALIDATION ──────────────────
load_dotenv()

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")   or None
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or None   # int as str for now
WEBSHARE_API_KEY = os.getenv("WEBSHARE_API_KEY") or None
WEBHOOK_URL      = os.getenv("WEBHOOK_URL", "https://checker.up.railway.app/webhook")

def _die(msg: str):
    print(f"❌ {msg}", file=sys.stderr); sys.exit(1)

if not TELEGRAM_TOKEN:   _die("TELEGRAM_TOKEN missing")
if not TELEGRAM_CHAT_ID: _die("TELEGRAM_CHAT_ID missing")
if not WEBSHARE_API_KEY: _die("WEBSHARE_API_KEY missing")
try:
    TELEGRAM_CHAT_ID = int(TELEGRAM_CHAT_ID)
except ValueError:
    _die("TELEGRAM_CHAT_ID must be integer‑like")

TG_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ────────────────── FASTAPI APP ──────────────────
app                  = FastAPI()
aiohttp_session:aiohttp.ClientSession|None = None
checking_task:asyncio.Task|None            = None
checking_active                              = False

# proxy pools & stats
proxy_pool      : deque[str]                     = deque()
proxy_stats     : defaultdict[str, dict]         = defaultdict(lambda: {"ok":0,"fail":0,"rt":None})
MAX_PROXY_FAILS = 3

# username queues
current_batch : deque[str] = deque()
BATCH_SIZE                 = 60

# ────────────────── UTIL ──────────────────
async def tg(method:str, **payload):
    """tiny Telegram helper"""
    async with aiohttp_session.post(f"{TG_API}/{method}", json=payload, timeout=10) as r:
        return await r.json()

async def tg_msg(text:str):
    return await tg("sendMessage", chat_id=TELEGRAM_CHAT_ID,
                    text=text, parse_mode="Markdown", disable_web_page_preview=True)

def brand_usernames(k:int)->list[str]:
    bases   = ["luxe","nova","vanta","kuro","aero","vela","mira","sola","ryze","zeal",
               "flux","nexa","orbi","lyra","echo","riva","pique","zara","kyro","kine"]
    suff    = ["ly","io","ex","us","on","fy"]
    out=set()
    while len(out)<k:
        u = random.choice(bases)+ (random.choice(suff) if random.random()<0.6 else "")
        if 3<=len(u)<=24: out.add(u)
    return list(out)

def pronounceable(k:int)->list[str]:
    vows,cons="aeiou","bcdfghjklmnpqrstvwxyz"
    patt=["CVCV","CVVC","VCVC","CCVC"]
    res=[]
    while len(res)<k:
        res.append(''.join(random.choice(vows if p=="V" else cons)
                           for p in random.choice(patt)))
    return res

# ────────────────── PROXY SCRAPING & VALIDATION ──────────────────
async def fetch_proxies()->list[str]:
    url="https://proxy.webshare.io/api/proxy/list/?page_size=100"
    hdr={"Authorization":f"Bearer {WEBSHARE_API_KEY}"}
    async with aiohttp_session.get(url,headers=hdr,timeout=15) as r:
        if r.status!=200:
            await tg_msg(f"❌ Webshare error HTTP {r.status}")
            return []
        data=await r.json()
        proxies=[]
        for p in data.get("results",[]):
            proxies.append(f"http://{p['username']}:{p['password']}@{p['proxy_address']}:{p['port']}")
        return proxies

async def validate_proxy(proxy:str, attempts:int=2)->tuple[str,bool,float|None]:
    url="https://www.tiktok.com/"
    hdr={"User-Agent":"Mozilla/5.0","Accept":"text/html"}
    best_rt=None
    for _ in range(attempts):
        t0=time.time()
        try:
            async with aiohttp_session.get(url,proxy=proxy,headers=hdr,timeout=8) as r:
                if r.status==200:
                    rt=time.time()-t0
                    best_rt=rt if best_rt is None else min(best_rt,rt)
                    return proxy,True,best_rt
        except: pass
    return proxy,False,None

async def refresh_proxies():
    raw=await fetch_proxies()
    if not raw:
        await tg_msg("⚠️ No proxies fetched.")
        return
    val_tasks=[validate_proxy(p) for p in raw]
    good=[]
    for proxy,ok,rt in await asyncio.gather(*val_tasks):
        if ok:
            good.append(proxy)
            proxy_stats[proxy]={"ok":0,"fail":0,"rt":rt}
    proxy_pool.clear(); proxy_pool.extend(good)
    await tg_msg(f"✅ Proxies ready: *{len(good)}* / {len(raw)}")

# ────────────────── TIKTOK AVAILABILITY ──────────────────
async def tiktok_available(username:str, proxy:str|None)->bool|None:
    url=f"https://www.tiktok.com/@{username}"
    hdr={"User-Agent":"Mozilla/5.0","Accept":"text/html"}
    try:
        async with aiohttp_session.get(url,headers=hdr,proxy=proxy,timeout=10,allow_redirects=False) as r:
            if r.status==404:  return True
            if r.status==200:  return False
    except: pass
    return None   # transient / proxy error

# ────────────────── CHECKER LOOP ──────────────────
async def checker():
    global checking_active
    await tg_msg("🟢 Checker started.")
    while checking_active:
        # ensure proxies
        if not proxy_pool:
            await tg_msg("⚠️ Proxy pool empty → rescraping")
            await refresh_proxies()
            await asyncio.sleep(5)
            continue

        # replenish usernames
        if not current_batch:
            current_batch.extend(brand_usernames(BATCH_SIZE//2)+pronounceable(BATCH_SIZE//2))
            await tg_msg(f"🔄 New batch → {len(current_batch)} usernames")

        username=current_batch.popleft()
        proxy   =proxy_pool[0]; proxy_pool.rotate(-1)

        result=await tiktok_available(username,proxy)
        if result is True:
            await tg_msg(f"✅ *{username}* is **available**")
            proxy_stats[proxy]["ok"]+=1
        elif result is False:
            proxy_stats[proxy]["ok"]+=1
        else: # None → error, count fail
            proxy_stats[proxy]["fail"]+=1
            if proxy_stats[proxy]["fail"]>=MAX_PROXY_FAILS:
                proxy_pool.remove(proxy)
                await tg_msg(f"⚠️ Removed bad proxy (fails>={MAX_PROXY_FAILS})")

        await asyncio.sleep(0.4)   # pacing

    await tg_msg("⏹️ Checker stopped.")

# ────────────────── TELEGRAM WEBHOOK ──────────────────
@app.post("/webhook")
async def webhook(req:Request):
    global checking_active, checking_task
    upd=await req.json()
    msg=upd.get("message",{})
    text=(msg.get("text") or "").strip()
    cid =msg.get("chat",{}).get("id")

    if cid!=TELEGRAM_CHAT_ID:  # ignore other chats
        return {"ok":True}

    if text=="/start":
        if checking_active:
            await tg_msg("Already running.")
        else:
            checking_active=True
            checking_task=asyncio.create_task(checker())
    elif text=="/stop":
        checking_active=False
    elif text=="/proxies":
        await refresh_proxies()
        good=len(proxy_pool)
        await tg_msg(f"🌐 Proxy pool size: *{good}*")
    elif text=="/usernames":
        await tg_msg(f"📋 Current batch left: *{len(current_batch)}*")
    else:
        await tg_msg("Commands: /start /stop /proxies /usernames")

    return {"ok":True}

# ────────────────── FASTAPI STARTUP ──────────────────
@app.on_event("startup")
async def on_start():
    global aiohttp_session
    aiohttp_session=aiohttp.ClientSession()

    # set Telegram webhook
    await tg("setWebhook", url=WEBHOOK_URL)

    # initial proxy scrape
    await refresh_proxies()

@app.on_event("shutdown")
async def on_stop():
    if aiohttp_session: await aiohttp_session.close()

# ────────────────── HEALTH ROUTE ──────────────────
@app.get("/health")
def health(): return {"status":"ok"}

# ────────────────── ASGI END ──────────────────
# run locally: uvicorn checker:app --reload --port 8000
