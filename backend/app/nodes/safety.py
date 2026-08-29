import asyncio
import atexit
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools

BACKEND = Path(__file__).resolve().parents[2]
log = logging.getLogger(__name__)


def _kill_mcp_children() -> int:
    """Kill lingering mcp_server.py subprocesses owned by this process.

    stdio_client terminates its process tree on a *clean* context exit, but a
    crash or an abnormal interpreter exit can leave orphaned children behind
    (observed as leftover mcp_server.py PIDs). Windows-only (CIM); guards the
    current process's own children so concurrent servers are untouched.
    Returns the number of PIDs killed.
    """
    if sys.platform != "win32":
        return 0
    killed = 0
    try:
        script = Path(MCP_SERVER_SCRIPT).name
        ps = (
            "Get-CimInstance Win32_Process | "
            "Where-Object {{ $_.Name -like 'python*' -and "
            "($_.CommandLine -match 'mcp_server.py') -and "
            "($_.ParentProcessId -eq {os.getpid()}) }} | "
            "Select-Object -ExpandProperty ProcessId"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout
        for line in out.splitlines():
            pid = line.strip()
            if not pid.isdigit():
                continue
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=10)
            killed += 1
    except Exception as e:  # pragma: no cover
        log.warning("mcp child cleanup failed: %s", e)
    return killed

with open(BACKEND / "processed" / "herb_mentions.json", encoding="utf-8") as f:
    herb_rows = json.load(f)

herbs_by_verse = {}
for row in herb_rows:
    herbs_by_verse.setdefault(row["verse_id"], []).append(row["herb"])

with open(BACKEND / "reference" / "herb_safety.json", encoding="utf-8") as f:
    SAFETY_DB = {entry["herb"]: entry for entry in json.load(f)}

LEGACY_CONTRAINDICATIONS = {
    "guggulu": "avoid during pregnancy",
    "trikatu": "use cautiously with active acid reflux",
}

MCP_SERVER_SCRIPT = str(BACKEND / "app" / "mcp_server.py")
MCP_READY = threading.Event()
_mcp_tool = None
MCP_ALIVE = False
LAST_CRASH_TIME = 0.0
RESPAWN_COOLDOWN = 30
RESPAWNING = threading.Lock()

atexit.register(_kill_mcp_children)


def _mcp_event_loop_thread(loop):
    loop.run_forever()


_bg_loop = asyncio.new_event_loop()
_bg_thread = threading.Thread(target=_mcp_event_loop_thread, args=(_bg_loop,), daemon=True)
_bg_thread.start()


_mcp_session_ref = None
_mcp_cm = None


async def _cleanup_old_context():
    global _mcp_session_ref, _mcp_cm
    if _mcp_session_ref:
        try:
            await _mcp_session_ref.__aexit__(None, None, None)
        except Exception:
            pass
        _mcp_session_ref = None
    if _mcp_cm:
        try:
            await _mcp_cm.__aexit__(None, None, None)
        except Exception:
            pass
        _mcp_cm = None


async def _init_mcp():
    global _mcp_tool, MCP_ALIVE, _mcp_session_ref, _mcp_cm
    try:
        _kill_mcp_children()
        params = StdioServerParameters(command=sys.executable, args=[MCP_SERVER_SCRIPT])
        _mcp_cm = stdio_client(params)
        read_stream, write_stream = await _mcp_cm.__aenter__()
        session = ClientSession(read_stream, write_stream)
        await session.__aenter__()
        await session.initialize()
        tools = await load_mcp_tools(session)
        _mcp_tool = next((t for t in tools if t.name == "check_herb_safety"), None)
        _mcp_session_ref = session
        MCP_ALIVE = True
        MCP_READY.set()
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        log.warning("MCP server failed to start: %s — falling back to local lookup", e)
        MCP_ALIVE = False
        MCP_READY.set()


async def _respawn_mcp():
    global _mcp_tool, MCP_ALIVE, LAST_CRASH_TIME, _mcp_session_ref, _mcp_cm
    if not RESPAWNING.acquire(blocking=False):
        return
    try:
        now = time.monotonic()
        if now - LAST_CRASH_TIME < RESPAWN_COOLDOWN:
            return
        LAST_CRASH_TIME = now
        log.info("Attempting MCP respawn...")
        stale = _kill_mcp_children()
        if stale:
            log.info("Killed %d stale mcp_server.py child PID(s)", stale)
        await _cleanup_old_context()
        params = StdioServerParameters(command=sys.executable, args=[MCP_SERVER_SCRIPT])
        _mcp_cm = stdio_client(params)
        read_stream, write_stream = await _mcp_cm.__aenter__()
        session = ClientSession(read_stream, write_stream)
        await session.__aenter__()
        await session.initialize()
        tools = await load_mcp_tools(session)
        _mcp_tool = next((t for t in tools if t.name == "check_herb_safety"), None)
        _mcp_session_ref = session
        MCP_ALIVE = True
        log.info("MCP respawn succeeded")
    except Exception as e:
        log.warning("MCP respawn failed: %s", e)
        MCP_ALIVE = False
    finally:
        RESPAWNING.release()


def _on_mcp_crash():
    global MCP_ALIVE, LAST_CRASH_TIME
    MCP_ALIVE = False
    LAST_CRASH_TIME = time.monotonic()
    log.warning("MCP subprocess crashed — falling back to JSON layer")
    asyncio.run_coroutine_threadsafe(_respawn_mcp(), _bg_loop)


asyncio.run_coroutine_threadsafe(_init_mcp(), _bg_loop)
MCP_READY.wait(timeout=10)


def _call_mcp_tool(herb_name: str) -> tuple[dict | None, str]:
    global MCP_ALIVE
    if _mcp_tool is None:
        return None, "unavailable"
    if not MCP_ALIVE:
        now = time.monotonic()
        if now - LAST_CRASH_TIME >= RESPAWN_COOLDOWN:
            log.info("Cooldown expired, attempting respawn before call...")
            future = asyncio.run_coroutine_threadsafe(_respawn_mcp(), _bg_loop)
            try:
                future.result(timeout=8)
            except Exception:
                pass
        if not MCP_ALIVE:
            return None, "json_fallback"
    try:
        future = asyncio.run_coroutine_threadsafe(
            _mcp_tool.ainvoke({"herb_name": herb_name}), _bg_loop
        )
        result = future.result(timeout=5)
        if isinstance(result, list) and result:
            first = result[0]
            if isinstance(first, dict) and "text" in first:
                text = first["text"]
            elif hasattr(first, "text"):
                text = first.text
            else:
                text = str(first)
        elif isinstance(result, str):
            text = result
        else:
            text = str(result)
        return json.loads(text), "mcp"
    except Exception as e:
        log.debug("MCP tool call failed for %s: %s", herb_name, e)
        _on_mcp_crash()
        return None, "json_fallback"


def _build_flags(herb: str, data: dict) -> list[str]:
    flags = []
    pregnancy = data.get("pregnancy_flag", "")
    if pregnancy and "no specific" not in pregnancy.lower():
        flags.append(f"pregnancy: {pregnancy}")
    for c in data.get("contraindications", [])[:2]:
        flags.append(c)
    dosha = data.get("dosha_caution", "")
    if dosha and "no specific" not in dosha.lower():
        flags.append(dosha)
    interactions = data.get("interactions", [])
    if interactions:
        flags.append(f"interacts with: {interactions[0]}")
    return [f"{herb}: {'; '.join(flags)}"] if flags else []


def _build_flags_from_db(herb: str, entry: dict) -> list[str]:
    return _build_flags(herb, entry)


def check_safety(state):
    verse_id = state["resolved_chapter"].get("verse_id")
    text = state["resolved_chapter"]["text"].lower()

    found = list(herbs_by_verse.get(verse_id, []))
    if not found:
        found = [row["herb"] for row in herb_rows if row["herb"] in text]

    found = sorted(set(found))
    flags = []
    sources = {}
    for h in found:
        mcp_data, source = _call_mcp_tool(h)
        if mcp_data and mcp_data.get("found"):
            flags.extend(_build_flags(h, mcp_data))
            sources[h] = source
        elif h in SAFETY_DB:
            flags.extend(_build_flags_from_db(h, SAFETY_DB[h]))
            sources[h] = "json_fallback"
        elif h in LEGACY_CONTRAINDICATIONS:
            flags.append(f"{h}: {LEGACY_CONTRAINDICATIONS[h]}")
            sources[h] = "legacy"
        else:
            flags.append(
                f"{h}: no safety monograph on file — use only in food quantities, "
                f"or confirm with a practitioner before medicinal use"
            )
            sources[h] = "uncovered"

    trace = state.get("trace", [])
    source_summary = ", ".join(f"{k}={v}" for k, v in sources.items()) or "none"
    step = (
        f"safety: herbs found [{', '.join(found) or 'none'}] via "
        f"{source_summary}; {len(flags)} flag(s) built"
    )

    verification_notes = []
    for h in found:
        entry = SAFETY_DB.get(h)
        if entry and not entry.get("modern_source_verified"):
            verification_notes.append(
                f"{h}: safety data from {entry.get('modern_source', 'modern source')} "
                f"- not yet independently cross-verified"
            )

    source_disagreements = []
    for h in found:
        entry = SAFETY_DB.get(h)
        if not entry or not entry.get("modern_source_verified"):
            continue
        pregnancy = (entry.get("pregnancy_flag") or "").lower()
        contraindications = " ".join(entry.get("contraindications", [])).lower()
        strong_caution = (
            "avoid" in pregnancy
            or "strictly avoid" in pregnancy
            or "toxic" in contraindications
        )
        if strong_caution:
            source_disagreements.append(
                f"{h}: classical texts describe its use, but modern sources flag strong "
                f"cautions (e.g., {entry.get('pregnancy_flag', 'toxicity')}) — "
                f"consult a practitioner before medicinal use"
            )

    return {
        "herbs_found": found,
        "safety_flags": flags,
        "safety_sources": sources,
        "verification_notes": verification_notes,
        "source_disagreements": source_disagreements,
        "trace": trace + [step],
    }
