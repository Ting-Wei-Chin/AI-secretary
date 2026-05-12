import os
from datetime import date
import anthropic
from database import (
    fetch_worker_roster,
    fetch_schedule_for_date,
    insert_schedule,
    insert_task,
    insert_contact,
    mark_schedule_done,
    reschedule,
    search_schedule,
    delete_schedule,
    update_schedule,
    fetch_groups,
)

SYSTEM_PROMPT_TEMPLATE = """You are a construction project assistant for a Taiwanese contractor managing a single worksite. You communicate exclusively in Traditional Chinese (繁體中文). Your user (老闆) sends messages via LINE — either voice (transcribed from Mandarin) or typed text — to manage workers, tasks, and permit stages.

<context>
There is only one worksite. Never ask which site. Messages arrive as transcribed speech or casual typed text — expect informal language, missing punctuation, and incomplete sentences. Use context to fill in gaps.

Today's date is {today_date}.

Your scheduled jobs: every day at 10:00 AM you push tomorrow's schedule; at 5:00 PM you send a check-in asking what was completed.

You have access to database tools. Always call the appropriate tool to save or retrieve data before replying.
</context>

<known_contacts>
{worker_roster}
</known_contacts>

<how_to_handle_each_message_type>

1. NEW INFORMATION (schedule, task, permit update)
   - Convert relative dates to actual calendar dates (YYYY-MM-DD)
   - Call save_schedule or save_task tool to store it
   - Reply: "好，已記錄：[one-line summary with actual date]"

2. SCHEDULE QUERY (e.g. "下週一有什麼？")
   - Call get_schedule tool for the relevant date(s)
   - Reply in day-by-day format

3. 8AM DAILY SUMMARY (triggered automatically)
   - Call get_schedule for today and tomorrow
   - If empty: "[date] 暫無行程"

4. 5PM CHECK-IN REPLY
   - For completed items: call mark_done tool
   - For rescheduled items: call reschedule_entry tool
   - Confirm what was updated

5. ACTION REQUESTS (e.g. "打電話給趙老闆")
   - Call save_task tool
   - Reply: "好，已記錄待辦：[action]"

6. NEW CONTACT
   - Call save_contact tool
   - Reply: "好，已新增聯絡人：[name]，[role]"

</how_to_handle_each_message_type>

<output_format>
Confirmations: one or two sentences, no lists.

Daily summaries:
【今日行程｜[月/日]】
・[人員] — [任務]

【明日行程｜[月/日]】
・[人員] — [任務]
</output_format>

<constraints>
- Always Traditional Chinese. Never Simplified.
- Always convert relative dates to YYYY-MM-DD before calling tools.
- Keep replies short. 老闆 is busy on a worksite.
- Never ask more than one clarifying question per message.
- Never use emojis.
- When asked about a specific person or task, always call search_schedule first before saying you don't know.
</constraints>"""

TOOLS = [
    {
        "name": "save_schedule",
        "description": "Save a worker's schedule entry to the database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                "worker_name": {"type": "string", "description": "Name of the worker"},
                "task": {"type": "string", "description": "Description of the task"},
            },
            "required": ["date", "worker_name", "task"],
        },
    },
    {
        "name": "save_task",
        "description": "Save a delegated task or action item to the database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Task description"},
                "assigned_to": {"type": "string", "description": "Person assigned (optional)"},
            },
            "required": ["description"],
        },
    },
    {
        "name": "save_contact",
        "description": "Save a new contact to the database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Contact name"},
                "role": {"type": "string", "description": "Their role or responsibility"},
            },
            "required": ["name", "role"],
        },
    },
    {
        "name": "get_schedule",
        "description": "Retrieve schedule entries for a specific date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
            },
            "required": ["date"],
        },
    },
    {
        "name": "mark_done",
        "description": "Mark a schedule entry as completed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                "worker_name": {"type": "string", "description": "Name of the worker"},
            },
            "required": ["date", "worker_name"],
        },
    },
    {
        "name": "send_to_group",
        "description": "Send a message to a LINE group by group name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "group_name": {"type": "string", "description": "Name of the group, e.g. 工班群"},
                "message": {"type": "string", "description": "Message to send to the group"},
            },
            "required": ["group_name", "message"],
        },
    },
    {
        "name": "delete_schedule",
        "description": "Delete a schedule entry from the database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                "worker_name": {"type": "string", "description": "Name of the worker"},
            },
            "required": ["date", "worker_name"],
        },
    },
    {
        "name": "update_schedule",
        "description": "Update the task description of an existing schedule entry.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                "worker_name": {"type": "string", "description": "Name of the worker"},
                "new_task": {"type": "string", "description": "Updated task description"},
            },
            "required": ["date", "worker_name", "new_task"],
        },
    },
    {
        "name": "search_schedule",
        "description": "Search schedule entries by worker name or task keyword.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Name or keyword to search for"},
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "reschedule_entry",
        "description": "Reschedule a worker's entry to a new date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "old_date": {"type": "string", "description": "Original date in YYYY-MM-DD"},
                "worker_name": {"type": "string", "description": "Name of the worker"},
                "new_date": {"type": "string", "description": "New date in YYYY-MM-DD"},
            },
            "required": ["old_date", "worker_name", "new_date"],
        },
    },
]


def handle_tool_call(name: str, inputs: dict) -> str:
    if name == "save_schedule":
        insert_schedule(inputs["date"], inputs["worker_name"], inputs["task"])
        return "saved"
    elif name == "save_task":
        insert_task(inputs["description"], inputs.get("assigned_to"))
        return "saved"
    elif name == "save_contact":
        insert_contact(inputs["name"], inputs["role"])
        return "saved"
    elif name == "get_schedule":
        rows = fetch_schedule_for_date(inputs["date"])
        if not rows:
            return "no entries"
        return "\n".join(f"{r['worker_name']} — {r['task']} ({r['status']})" for r in rows)
    elif name == "mark_done":
        mark_schedule_done(inputs["date"], inputs["worker_name"])
        return "marked done"
    elif name == "send_to_group":
        groups = fetch_groups()
        target = next((g for g in groups if g["name"] == inputs["group_name"]), None)
        if not target:
            return f"group '{inputs['group_name']}' not found in database"
        import asyncio, httpx, os
        async def _push():
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://api.line.me/v2/bot/message/push",
                    headers={"Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}"},
                    json={"to": target["group_id"], "messages": [{"type": "text", "text": inputs["message"]}]},
                )
        asyncio.get_event_loop().run_until_complete(_push())
        return "sent"
    elif name == "delete_schedule":
        delete_schedule(inputs["date"], inputs["worker_name"])
        return "deleted"
    elif name == "update_schedule":
        update_schedule(inputs["date"], inputs["worker_name"], inputs["new_task"])
        return "updated"
    elif name == "search_schedule":
        rows = search_schedule(inputs["keyword"])
        if not rows:
            return "no entries found"
        return "\n".join(f"{r['date']} {r['worker_name']} — {r['task']} ({r['status']})" for r in rows)
    elif name == "reschedule_entry":
        reschedule(inputs["old_date"], inputs["worker_name"], inputs["new_date"])
        return "rescheduled"
    return "unknown tool"


def build_system_prompt() -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        today_date=date.today().strftime("%Y/%m/%d"),
        worker_roster=fetch_worker_roster(),
    )


def ask_claude(user_message: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    messages = [{"role": "user", "content": user_message}]

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=build_system_prompt(),
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = handle_tool_call(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        else:
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            return "（無回覆）"
