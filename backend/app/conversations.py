import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DATA_FILE = BACKEND / "conversations.jsonl"

_lock = threading.Lock()
_MAX_TURNS = 60


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load():
    if not DATA_FILE.exists():
        return []
    rows = []
    for line in DATA_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _save(rows):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _title_for(first_user_text):
    text = " ".join((first_user_text or "").split())
    return (text[:60] + "…") if len(text) > 60 else (text or "New conversation")


def list_conversations():
    with _lock:
        rows = _load()
    summaries = [
        {
            "id": r["id"],
            "title": r["title"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "message_count": len(r["messages"]),
        }
        for r in rows
    ]
    summaries.sort(key=lambda r: r["updated_at"], reverse=True)
    return summaries


def get_conversation(conversation_id):
    with _lock:
        rows = _load()
    for r in rows:
        if r["id"] == conversation_id:
            return r
    return None


def _upsert(conversation_id, title, user_msg, assistant_msg):
    with _lock:
        rows = _load()
        record = None
        for r in rows:
            if r["id"] == conversation_id:
                record = r
                break
        now = _now()
        if record is None:
            record = {
                "id": conversation_id,
                "title": title,
                "created_at": now,
                "updated_at": now,
                "messages": [],
            }
            rows.append(record)
        if user_msg:
            record["messages"].append(
                {"id": str(uuid.uuid4()), "role": "user", **user_msg, "timestamp": now}
            )
        if assistant_msg:
            record["messages"].append(
                {
                    "id": str(uuid.uuid4()),
                    "role": "assistant",
                    **assistant_msg,
                    "timestamp": now,
                }
            )
        record["messages"] = record["messages"][-_MAX_TURNS:]
        record["updated_at"] = now
        _save(rows)
        return record


def save_turn(conversation_id, user_message, assistant_payload):
    conversation_id = conversation_id or str(uuid.uuid4())
    title = _title_for(user_message)
    user_msg = {"content": user_message}
    assistant_payload = dict(assistant_payload)
    content = assistant_payload.pop("content", None)
    if content is None:
        content = assistant_payload.pop("answer", "")
    assistant_msg = {"content": content}
    assistant_msg.update(assistant_payload)
    record = _upsert(conversation_id, title, user_msg, assistant_msg)
    dosha = assistant_payload.get("dosha")
    if dosha:
        with _lock:
            rows = _load()
            for r in rows:
                if r["id"] == conversation_id and r.get("dosha_profile") != dosha:
                    r["dosha_profile"] = dosha
                    _save(rows)
                    break
    return record["id"], record["title"]


def delete_conversation(conversation_id):
    with _lock:
        rows = _load()
        remaining = [r for r in rows if r["id"] != conversation_id]
        deleted = len(remaining) != len(rows)
        if deleted:
            _save(remaining)
        return deleted