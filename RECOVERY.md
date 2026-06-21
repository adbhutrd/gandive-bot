# 🚀 GandiveBot — Recovery Guide

**Everything is saved on GitHub and in PM2. Here's how to get back up after the session resets.**

---

## 📦 What Was Built (All Running Before Session End)

| Service | What It Does | How to Restart |
|---|---|---|
| 🤖 **GandiveBot** | Crypto signal bot @GandiveBot | `bash startup.sh` |
| 💰 **Ko-fi Webhook** | Auto-activates premium on payment | Auto-starts with bot |
| 📊 **Dashboard** | Monitor signals & users | Auto-starts with bot |
| 🌐 **Tunnel** | HTTPS for webhook | `bash startup.sh` |
| 📰 **AISAMACHAR** | AI news bot with subscribers | Auto-starts via PM2 |
| 🌍 **Landing Page** | `adbhutrd.github.io/gandive-bot/` | Already live |
| 💼 **AI Automation Pro** | `adbhutrd.github.io/ai-automation-pro/` | Enable Pages in settings |

---

## 🔥 Quick Recovery (1 Command)

```bash
cd /home/enishshah2/gandive_bot && bash startup.sh
```

This restarts all bots, webhook, dashboard, and tunnel.

---

## 🔧 Manual Recovery Steps

### If PM2 Is Still Running
```bash
pm2 resurrect
pm2 status
```

### If PM2 Was Lost (Fresh Start)
```bash
cd /home/enishshah2/gandive_bot

# Start bot + webhook + dashboard
source venv/bin/activate
pm2 start venv/bin/python --name gandive-bot -- bot.py
pm2 start venv/bin/python --name gandive-webhook -- webhook_server.py
pm2 start venv/bin/python --name gandive-dashboard -- dashboard.py

# Start tunnel
pm2 start /usr/local/bin/cloudflared --name gandive-tunnel -- tunnel --url http://localhost:5000 --no-autoupdate

# Start AISAMACHAR
cd /home/enishshah2/freebuff
pm2 start ecosystem.config.cjs --only aisamachar

# Save state
pm2 save
```

---

## 🎯 The Most Important Thing: Update Ko-fi Webhook URL

Every time the tunnel restarts, the **trycloudflare.com URL changes**.

**You must update it in Ko-fi:**
1. Go to https://ko-fi.com/manage/webhooks
2. Get the new URL: `pm2 logs gandive-tunnel --lines 5 --nostream`
3. Look for: `https://XXXX.trycloudflare.com`
4. Paste as: `https://XXXX.trycloudflare.com/kofi-webhook`
5. Verification token is already: `52d93670-0fd0-47e2-a785-8249207835fb`
6. Click **Save**

---

## 📋 What's Saved Where

| Project | GitHub Repo | Local Path |
|---|---|---|
| GandiveBot | `github.com/adbhutrd/gandive-bot` | `/home/enishshah2/gandive_bot` |
| AISAMACHAR | `github.com/adbhutrd/aisamachar` | `/home/enishshah2/freebuff` |
| AI Automation Pro | `github.com/adbhutrd/ai-automation-pro` | `/home/enishshah2/ai-automation-pro` |

---

## 💎 Key Facts for When You Come Back

- **Bot username:** @GandiveBot
- **Landing page:** https://adbhutrd.github.io/gandive-bot/
- **Ko-fi page:** https://ko-fi.com/adbhutrd
- **Ko-fi token:** `52d93670-0fd0-47e2-a785-8249207835fb`
- **Premium price:** $9.99/mo | Elite $24.99/mo
- **Referral reward:** 7 days free per referral
- **Admin user ID:** 7837847803 (you)
- **AISAMACHAR subscribers:** Already have a Telegram channel with audience

---

## 🔜 Next Steps When You Return

1. Run `bash startup.sh` to restore everything
2. Update the Ko-fi webhook URL (it changes every tunnel restart)
3. Message @GandiveBot → send `/start` to test it
4. Post the Reddit threads I wrote for you
5. Enable GitHub Pages for AI Automation Pro

---

*If anything breaks, just tell the AI agent: "Run the GandiveBot recovery" and it will know what to do.*
