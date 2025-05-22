# Deployment Checklist for Docker + Railway

## Before Deploying
- [ ] Confirm all secrets are set in Railway Variables:
  - `TELEGRAM_TOKEN`
  - `TELEGRAM_CHAT_ID`
  - `WEBSHARE_API_KEY`
  - `WEBHOOK_URL` (your Railway app webhook URL)
- [ ] Verify your Dockerfile is present and correctly configured
- [ ] Ensure `requirements.txt` includes all dependencies (e.g. `fastapi`, `uvicorn`, `aiohttp`)

---

## Deployment Steps
- [ ] Push latest code and Dockerfile to GitHub
- [ ] Link GitHub repo to Railway project
- [ ] Confirm Railway’s start command is:


---

- [ ] Trigger deployment on Railway
- [ ] Wait for build and deploy to finish successfully

---

## Post Deployment
- [ ] Get Railway deployment URL (e.g., `https://checker.up.railway.app`)
- [ ] Set Telegram webhook URL via:
```bash
curl -F "url=https://checker.up.railway.app/webhook" https://api.telegram.org/bot<TELEGRAM_TOKEN>/setWebhook
