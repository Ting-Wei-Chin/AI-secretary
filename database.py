import os
from supabase import create_client, Client

_client: Client | None = None


def get_db() -> Client:
    global _client
    if _client is None:
        _client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return _client


def fetch_worker_roster() -> str:
    rows = get_db().table("contacts").select("name, role").execute().data
    if not rows:
        return "（尚無聯絡人）"
    return "\n".join(f"{r['name']} — {r['role']}" for r in rows)


def fetch_schedule_for_date(date_str: str) -> list[dict]:
    return (
        get_db()
        .table("schedules")
        .select("*")
        .eq("date", date_str)
        .execute()
        .data
    )


def insert_schedule(date_str: str, worker_name: str, task: str):
    get_db().table("schedules").insert({
        "date": date_str,
        "worker_name": worker_name,
        "task": task,
        "status": "pending",
    }).execute()


def insert_task(description: str, assigned_to: str | None = None):
    get_db().table("tasks").insert({
        "description": description,
        "assigned_to": assigned_to,
        "status": "pending",
    }).execute()


def insert_contact(name: str, role: str):
    get_db().table("contacts").upsert({"name": name, "role": role}).execute()


def mark_schedule_done(date_str: str, worker_name: str):
    get_db().table("schedules").update({"status": "done"}).eq("date", date_str).eq("worker_name", worker_name).execute()


def reschedule(old_date: str, worker_name: str, new_date: str):
    get_db().table("schedules").update({"date": new_date, "status": "pending"}).eq("date", old_date).eq("worker_name", worker_name).execute()


def delete_schedule(date_str: str, worker_name: str):
    get_db().table("schedules").delete().eq("date", date_str).eq("worker_name", worker_name).execute()


def update_schedule(date_str: str, worker_name: str, new_task: str):
    get_db().table("schedules").update({"task": new_task}).eq("date", date_str).eq("worker_name", worker_name).execute()


def fetch_groups() -> list[dict]:
    return get_db().table("groups").select("name, group_id").execute().data


def search_schedule(keyword: str) -> list[dict]:
    return (
        get_db()
        .table("schedules")
        .select("*")
        .ilike("worker_name", f"%{keyword}%")
        .execute()
        .data
    ) or (
        get_db()
        .table("schedules")
        .select("*")
        .ilike("task", f"%{keyword}%")
        .execute()
        .data
    )
