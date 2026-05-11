# AI Secretary — LINE Bot for Construction Site Management

A LINE chatbot that acts as a personal assistant for a construction site manager. It receives voice and text messages, transcribes Mandarin audio, processes requests with Claude AI, and manages schedules/tasks in a database.

---

## Architecture

```
Dad (LINE)
    │
    │  voice / text
    ▼
LINE Messaging API
    │
    │  webhook POST /webhook
    ▼
FastAPI Server (Railway)
    │
    ├─── voice message? ──► OpenAI Whisper ──► transcribed text
    │
    ├─── text message ──────────────────────► Claude (Anthropic)
    │                                              │
    │                                    reads system prompt
    │                                    calls database tools
    │                                              │
    │                                         Supabase
    │                                              │
    │◄─────────────────────── reply text ──────────┘
    │
    ▼
LINE (reply sent back to Dad)
```

### Scheduled Jobs (APScheduler)
```
10:00 AM daily  ──►  push tomorrow's schedule to all users
 5:00 PM daily  ──►  push check-in: "今天完成了嗎？有需要改期的嗎？"
```

---

## Tech Stack

| Piece | Tool | Purpose |
|---|---|---|
| Chat interface | LINE Messaging API | Receives and sends messages |
| Voice → Text | OpenAI Whisper (`whisper-1`) | Transcribes Mandarin voice messages |
| AI Brain | Anthropic Claude (`claude-sonnet-4-6`) | Understands requests, calls tools, replies in Traditional Chinese |
| Database | Supabase (PostgreSQL) | Stores schedules, tasks, contacts |
| Backend server | FastAPI + Uvicorn | Webhook handler, scheduler |
| Hosting | Railway | Cloud deployment, free tier |
| Scheduling | APScheduler | Triggers daily push messages |

---

## File Structure

```
├── main.py              # FastAPI app, LINE webhook handler, APScheduler jobs
├── claude_client.py     # Claude API call, system prompt, tool definitions
├── whisper_client.py    # Downloads audio from LINE, sends to Whisper
├── database.py          # All Supabase read/write functions
├── requirements.txt     # Python dependencies
├── .env                 # Secret keys (never commit this)
├── .env.example         # Template showing required env vars
├── supabase_schema.sql  # SQL to create tables (run once in Supabase SQL Editor)
└── README.md            # This file
```

---

## Database Schema (Supabase)

### `contacts`
Stores known workers and contacts.
```sql
id          bigint  primary key
name        text    unique        -- e.g. 淂溱
role        text                  -- e.g. 顧問
```

### `schedules`
Stores worker schedule entries per date.
```sql
id           bigint  primary key
date         date                 -- YYYY-MM-DD
worker_name  text
task         text
status       text    default 'pending'   -- pending | done | rescheduled
```

### `tasks`
Stores delegated action items (to-dos).
```sql
id           bigint  primary key
description  text
assigned_to  text    nullable
status       text    default 'pending'   -- pending | done
created_at   timestamptz
```

> Row Level Security is disabled on all three tables. This is intentional — the server uses the anon key but operates as a trusted backend.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in all values.

| Variable | Where to get it |
|---|---|
| `LINE_CHANNEL_SECRET` | LINE Developers Console → Basic settings |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Developers Console → Messaging API → Issue |
| `OPENAI_API_KEY` | platform.openai.com → API keys |
| `ANTHROPIC_API_KEY` | console.anthropic.com → API keys |
| `SUPABASE_URL` | Supabase → Project Settings → API → Project URL |
| `SUPABASE_KEY` | Supabase → Project Settings → API → anon public key |
| `LINE_USER_ID` | Comma-separated LINE user IDs to receive push messages (e.g. `Uabc123,Udef456`) |

---

## How Claude Works

Claude is given a system prompt (`claude_client.py`) that tells it:
- Today's date (injected at runtime)
- The known contacts list (fetched from Supabase at runtime)
- How to handle each message type (new info, queries, check-in replies)
- The scheduled reminder times (10am and 5pm)

Claude uses **tool use** to interact with the database. Instead of just generating text, it calls tools like `save_schedule`, `get_schedule`, `mark_done`, etc. The server executes the tool and feeds the result back to Claude, which then generates the final reply.

### Available Tools
| Tool | What it does |
|---|---|
| `save_schedule` | Insert a new schedule entry |
| `save_task` | Insert a new to-do item |
| `save_contact` | Insert a new contact |
| `get_schedule` | Fetch schedules for a specific date |
| `search_schedule` | Search schedules by worker name or task keyword |
| `mark_done` | Mark a schedule entry as completed |
| `reschedule_entry` | Move a schedule entry to a new date |

---

## Webhook Flow

LINE requires a 200 response within 1 second. To avoid timeouts (Claude takes 2–5 seconds):

1. Webhook receives the request → immediately returns `200 OK`
2. Spins up a background task (`asyncio.create_task`) to process the message
3. Background task calls Whisper (if audio) → Claude → sends reply via LINE push API

---

## Known Issues & Fixes

| Problem | Cause | Fix |
|---|---|---|
| 500 on Supabase write | Row Level Security blocked anon key | Disabled RLS on all tables via SQL Editor |
| 500 Invalid API key | `SUPABASE_URL` was set to dashboard URL, not project API URL | Use the `https://xxx.supabase.co` URL from Project Settings |
| LINE webhook 499 timeout | Claude processing exceeded LINE's 1-second timeout | Moved processing to `asyncio.create_task`, returns 200 immediately |
| Supabase `InvalidAPIKey` | Old supabase-py didn't support new `sb_publishable_` key format | Upgraded supabase to `>=2.10.0` |

---

## Changing Reminder Times

Edit `main.py` lines 23–24:
```python
scheduler.add_job(send_morning_summary, CronTrigger(hour=10, minute=0, timezone="Asia/Taipei"))
scheduler.add_job(send_evening_checkin, CronTrigger(hour=17, minute=0, timezone="Asia/Taipei"))
```
Use 24-hour format. Push to GitHub — Railway redeploys automatically.

Also update the system prompt in `claude_client.py` so Claude knows the correct times:
```
Your scheduled jobs: every day at 10:00 AM you push tomorrow's schedule; at 5:00 PM you send a check-in...
```

---

## Adding a New Contact

Tell the bot:
> 新增聯絡人：XXX，負責XXX

Claude will call `save_contact` and store it in Supabase. The contact will appear in Claude's context on the next message.

## Adding Yourself to Push Messages

1. Send any message to the bot
2. Check Railway → Deploy Logs for `LINE USER ID: Uxxxxx`
3. Add your ID to `LINE_USER_ID` in Railway Variables: `dad_id,your_id`

---

## Local Development

```bash
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
cp .env.example .env   # fill in your keys
uvicorn main:app --reload
```

To test locally with LINE, use [ngrok](https://ngrok.com) to expose your local server:
```bash
ngrok http 8000
# copy the https URL → paste into LINE webhook URL
```
