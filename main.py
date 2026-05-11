import os
import hashlib
import hmac
import base64
from contextlib import asynccontextmanager

import asyncio
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import httpx

from claude_client import ask_claude
from whisper_client import transcribe_audio

load_dotenv()

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(send_morning_summary, CronTrigger(hour=10, minute=0, timezone="Asia/Taipei"))
    scheduler.add_job(send_evening_checkin, CronTrigger(hour=17, minute=0, timezone="Asia/Taipei"))
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)


def verify_line_signature(body: bytes, signature: str) -> bool:
    secret = os.environ["LINE_CHANNEL_SECRET"].encode()
    digest = hmac.new(secret, body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)


async def send_line_message(text: str):
    user_id = os.environ["LINE_USER_ID"]
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "to": user_id,
                "messages": [{"type": "text", "text": text}],
            },
        )


async def send_morning_summary():
    reply = ask_claude("【系統觸發】請傳送明天的行程摘要。")
    await send_line_message(reply)


async def send_evening_checkin():
    await send_line_message("今天的事情都完成了嗎？有需要改期的嗎？")


async def process_event(event: dict):
    msg = event["message"]
    reply_token = event["replyToken"]
    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]

    if msg["type"] == "text":
        user_text = msg["text"]
    elif msg["type"] == "audio":
        audio_url = f"https://api-data.line.me/v2/bot/message/{msg['id']}/content"
        user_text = transcribe_audio(audio_url, token)
    else:
        return

    reply_text = ask_claude(user_text)

    async with httpx.AsyncClient() as client:
        await client.post(
            "https://api.line.me/v2/bot/message/reply",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "replyToken": reply_token,
                "messages": [{"type": "text", "text": reply_text}],
            },
        )


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    if not verify_line_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    import json
    payload = json.loads(body)

    for event in payload.get("events", []):
        if event.get("type") == "message":
            asyncio.create_task(process_event(event))

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}
