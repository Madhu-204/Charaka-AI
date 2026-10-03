import asyncio
import hashlib
import json
import mimetypes
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from langchain_core.callbacks import BaseCallbackHandler
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from app.graph import charaka_agent
from app import auth, cache, conversations, ratelimit, stats, trace
from app.nodes.summarize import build_hindi_summary, build_summary
from app.nodes.synthesis import MAX_HISTORY_TURNS, SynthesisUnavailable
# Confidence bands live in the retriever because that is where they are derived
# from the cosine score. They were duplicated here as bare literals, which meant
# retuning one silently left the API reporting a different band than the agent
# used. app.graph above already imports the retriever, so this costs nothing.
from app.nodes.retriever import HIGH_SCORE, MEDIUM_SCORE

BACKEND = Path(__file__).resolve().parents[1]
FEEDBACK_LOG = BACKEND / "feedback_log.jsonl"
REFERENCE = BACKEND / "reference"
PROCESSED = BACKEND / "processed"
TRACES_DIR = BACKEND / "traces"
EVAL_RESULTS = BACKEND / "eval_results.json"

load_dotenv()
app = FastAPI()

API_KEY = os.getenv("CHARAKA_API_KEY")
ADMIN_KEY = os.getenv("CHARAKA_ADMIN_KEY")
# Accounts are mandatory by default: every private route needs a real session
# so one person can never read another's conversations. Set to 0 only for
# single-user local work, which reopens the legacy shared-key mode.
AUTH_REQUIRED = os.getenv("CHARAKA_AUTH_REQUIRED", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
_QUERY_CACHE = cache.LRUCache(
    capacity=int(os.getenv("CHARAKA_CACHE_SIZE", "64")),
    ttl=int(os.getenv("CHARAKA_CACHE_TTL", "3600")),
)
_LIMITER = ratelimit.RateLimiter(
    per_minute=int(os.getenv("CHARAKA_RATE_LIMIT", "30")),
    burst=int(os.getenv("CHARAKA_RATE_BURST", "60")),
)
_GATE = ratelimit.ConcurrencyGate(
    slots=int(os.getenv("CHARAKA_LLM_CONCURRENCY", "2")),
    timeout=float(os.getenv("CHARAKA_LLM_QUEUE_TIMEOUT", "45")),
)
# Ceiling on graph steps per request. The graph is acyclic and its longest path is
# 11 nodes, so this never fires today; it exists so that adding a back-edge later
# (a grounding retry, say) cannot turn into an unbounded loop. Passed per call as
# `recursion_limit` because LangGraph reads it from the runtime config, not from
# compile() — graph.py compiles with no arguments and must stay that way.
_RECURSION_LIMIT = int(os.getenv("CHARAKA_RECURSION_LIMIT", "25"))
# Wall-clock ceiling for one streamed request, enforced on the worker thread.
# Each LLM call is individually capped at timeout=60, so a request can otherwise
# chain router (60s) + synthesis (60s) + summary (60s) and blow past the client's
# own 180s abort while still holding one of only two Groq slots. 90s sits under
# that abort so the server gives up first and can say why.
_REQUEST_DEADLINE_S = float(os.getenv("CHARAKA_REQUEST_DEADLINE_S", "90"))
# Requests arrive as bare `str` in the two models below. Without a cap a client can
# post megabytes straight into the retrieval and synthesis prompt path, which costs
# tokens before any guardrail downstream gets a say.
MAX_QUERY_CHARS = int(os.getenv("CHARAKA_MAX_QUERY_CHARS", "2000"))
_FEEDBACK_STATS = stats.FeedbackStats(FEEDBACK_LOG)


class _TokenUsage(BaseCallbackHandler):
    """Per-request token accounting read from the provider's own usage report.

    This replaces a count of whitespace-separated words in the streamed answer,
    which was wrong in the expensive direction: it ignored every prompt token and
    the entire route_tools LLM call, so the reported figure was a small fraction of
    what the request actually cost. That matters because Groq's free tier is a
    shared 8000 TPM window, and synthesis.py already flags a case where two calls
    at MAX_REQUEST_TOKENS could exceed it.

    One instance per request, passed through the graph config. No module state, so
    concurrent requests cannot read each other's numbers.
    """

    def __init__(self) -> None:
        self.prompt = 0
        self.completion = 0
        self.calls = 0

    def on_llm_end(self, response, **kwargs) -> None:  # noqa: ARG002
        self.calls += 1
        usage = (getattr(response, "llm_output", None) or {}).get("token_usage") or {}
        if not usage:
            # Newer langchain-core versions attach usage to the message instead.
            try:
                usage = response.generations[0][0].message.usage_metadata or {}
            except (AttributeError, IndexError, KeyError, TypeError):
                usage = {}
        self.prompt += int(
            usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        )
        self.completion += int(
            usage.get("completion_tokens") or usage.get("output_tokens") or 0
        )

    @property
    def total(self) -> int:
        return self.prompt + self.completion


def _graph_config(usage: _TokenUsage) -> dict:
    return {"recursion_limit": _RECURSION_LIMIT, "callbacks": [usage]}


def _key_matches(provided: Optional[str], expected: Optional[str]) -> bool:
    if not expected:
        return True
    if not provided:
        return False
    return secrets.compare_digest(provided, expected)


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def current_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> Optional[dict]:
    """Resolve the caller to a registered account.

    A valid session token identifies a real user and scopes their data. The
    shared CHARAKA_API_KEY still works, but resolves to None so that key-based
    callers fall back to the legacy unscoped behaviour instead of silently
    sharing one account's data.
    """
    token = _bearer_token(authorization)
    user = auth.resolve_token(token) if token else None
    if user:
        request.state.user_id = user["id"]
        return user
    if not AUTH_REQUIRED and _key_matches(x_api_key, API_KEY):
        return None
    raise HTTPException(
        status_code=401,
        detail="sign in to continue",
        headers={"WWW-Authenticate": "Bearer"},
    )


def optional_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> Optional[dict]:
    """Same as current_user but never raises; used by public routes."""
    token = _bearer_token(authorization)
    user = auth.resolve_token(token) if token else None
    if user:
        request.state.user_id = user["id"]
    return user


def _owner(request: Request) -> str:
    return getattr(request.state, "user_id", None) or "shared"


def guard_ask(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> None:
    current_user(request, authorization, x_api_key)
    client_id = getattr(request.state, "user_id", None) or x_api_key or (
        request.client.host if request.client else "local"
    )
    if not _LIMITER.allow(client_id):
        raise HTTPException(
            status_code=429,
            detail="rate limit exceeded — slow down and retry shortly",
            headers={"Retry-After": "5"},
        )


def guard_private(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> None:
    """Gate conversation, document and feedback routes.

    These were previously world-readable and world-writable: any client could
    list, read and delete every stored conversation, and read or delete another
    user's uploaded documents by guessing their session id. A registered
    session is now required and scopes the caller to their own rows.
    """
    current_user(request, authorization, x_api_key)


def guard_admin(x_api_key: Optional[str] = Header(default=None)) -> None:
    """Gate /stats, /traces and /eval/run.

    /traces and /stats expose every user's query text. /eval/run drives the
    LLM with no quota of its own, so leaving it open is an unmetered spend.
    """
    if not _key_matches(x_api_key, ADMIN_KEY):
        raise HTTPException(
            status_code=401,
            detail="admin API key required",
        )


STHANA_ORDER = ["sutrasthana", "vimanasthana", "sharirasthana", "chikitsasthana"]
STHANA_TITLES = {
    "sutrasthana": "Sutra Sthana — General Principles",
    "vimanasthana": "Vimana Sthana — Assessment & Physiology",
    "sharirasthana": "Sharira Sthana — Body & Embryology",
    "chikitsasthana": "Chikitsa Sthana — Therapeutics",
}

try:
    _CORPUS = json.loads((PROCESSED / "charaka_structured.json").read_text(encoding="utf-8"))
except Exception:  # noqa: BLE001
    _CORPUS = []

# Answers are cached in-process for the TTL, so a re-index that changes the
# corpus would otherwise keep serving pre-change answers. Stamp the corpus into
# the cache key so a rebuild invalidates old entries without a restart.
_CORPUS_VERSION = hashlib.sha256(
    json.dumps(_CORPUS, sort_keys=True, ensure_ascii=False).encode("utf-8")
).hexdigest()[:16]
def _allowed_origins() -> list:
    raw = os.getenv("CHARAKA_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

VERSE_TEXT_CHARS = 280

STAGE_LABELS = {
    "check_emergency": "Checking for red flags",
    "tag_dosha": "Analyzing dosha pattern",
    "expand_query": "Expanding query",
    "route_tools": "Choosing retrieval strategy",
    "direct_answer": "Answering directly",
    "retrieve": "Searching 2,490 verses",
    "clarify": "Asking to disambiguate",
    "check_safety": "Checking herb safety",
    "synthesize": "Grounding answer in classical texts",
    "grounding": "Verifying citations",
    "attribution": "Aligning answer sentences to sources",
}


class AskRequest(BaseModel):
    query: str = Field(..., max_length=MAX_QUERY_CHARS)
    history: Optional[List[dict]] = None
    conversation_id: Optional[str] = None
    dosha_profile: Optional[str] = None
    lang: Optional[Literal["en", "hin"]] = None
    doc_session: Optional[str] = None
    # True when the user pressed Regenerate: overwrite the trailing turn in
    # place instead of appending a duplicate question/answer pair.
    regenerate: bool = False


class FeedbackRequest(BaseModel):
    query: str = Field(..., max_length=MAX_QUERY_CHARS)
    rating: Literal["up", "down"]
    message_id: Optional[str] = None


class RegisterRequest(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=200)
    name: str = Field(default="", max_length=80)


class LoginRequest(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=200)
    answer: Optional[str] = None
    trace: Optional[List[str]] = None
    dosha: Optional[str] = None
    category_tag: Optional[str] = None
    chapter: Optional[str] = None


def _confidence_band(score) -> str:
    if score > HIGH_SCORE:
        return "high"
    if score > MEDIUM_SCORE:
        return "medium"
    return "low"


def _verse_summary(candidate: dict) -> dict:
    score = float(candidate["score"])
    return {
        "verse_id": candidate["verse_id"],
        "chapter": f"{candidate['meta']['sthana']}/{candidate['meta']['chapter']}",
        "score": round(score, 4),
        "text": candidate.get("text", "")[:VERSE_TEXT_CHARS],
        "confidence": _confidence_band(score),
    }


def build_response(result: dict, latency_ms: Optional[int] = None) -> dict:
    rc = result.get("resolved_chapter") or {}
    is_emergency = result["is_emergency"]
    # A scope refusal is terminal like an emergency: nothing was retrieved, so
    # chapter/category/dosha must be null rather than stale defaults.
    is_out_of_scope = bool(result.get("is_out_of_scope"))
    # A conversational reply is terminal for the same reason: nothing was retrieved,
    # so chapter/category/dosha must be null rather than stale. Including it here
    # also keeps `attribution` and `reasoning_trace` off the response, since neither
    # means anything without a passage behind it.
    is_direct = bool(result.get("is_direct_answer"))
    no_context = is_emergency or is_out_of_scope or is_direct
    # An answer that cites nothing checkable still reads as authoritative prose,
    # which is the one grounding failure a user cannot catch by reading. It ships
    # — the retrieved context was usually relevant and discarding it would help
    # nobody — but it must not carry the confidence the drafting asked for.
    ungrounded = bool(result.get("grounding_ungrounded")) and not no_context
    # Whether a draft was ever produced is a separate question from whether the
    # answer has context. Clarification sits apart from `no_context`: when it fires
    # after retrieval the chapter is real and worth showing, but `route_after_retrieve`
    # branches to `clarify` ahead of check_safety and synthesize, so it skipped the
    # draft either way and must not be counted as one attempt.
    no_synthesis = no_context or bool(result.get("is_clarification"))
    response = {
        "answer": result["final_answer"],
        "is_emergency": is_emergency,
        "is_out_of_scope": is_out_of_scope,
        "is_direct_answer": is_direct,
        "scope_category": result.get("scope_category"),
        "is_clarification": bool(result.get("is_clarification")),
        "confidence": "low" if ungrounded else result.get("confidence"),
        "chapter": rc.get("meta", {}).get("chapter") if not no_context else None,
        "category_tag": rc.get("meta", {}).get("category_tag") if not no_context else None,
        "safety_flags": result.get("safety_flags", []),
        "dosha": result.get("dosha") if not no_context else None,
        "latency_ms": latency_ms,
        # 0 = nothing was ever drafted (emergency, refusal, direct reply or a
        # clarifying question), 1 = drafted once, 2 = the citation check rejected
        # the first draft and it was rewritten. Surfaced because a retried answer
        # carries two synthesis calls, visible in both latency and token spend.
        "synthesis_attempts": 0 if no_synthesis else result.get("synthesis_attempts", 1),
        # The UI keys its blocking banner off this rather than parsing notes.
        "is_ungrounded": ungrounded,
        "used_documents": bool(result.get("used_documents")),
        "document_names": sorted(
            {d.get("doc", "uploaded document") for d in result.get("user_docs", [])}
        ),
    }
    if not no_context:
        response["attribution"] = result.get("attribution", [])
        response["reasoning_trace"] = {
            "steps": result.get("trace", []),
            "canonical_term": result.get("canonical_term"),
            "retrieved_verses": [_verse_summary(c) for c in result.get("retrieved", [])],
            "confidence_score": result.get("confidence_score"),
            "herbs_found": result.get("herbs_found", []),
            "dosha_scores": result.get("dosha_scores"),
            "safety_sources": result.get("safety_sources"),
            "verification_notes": result.get("verification_notes", []),
            "source_disagreements": result.get("source_disagreements", []),
            "grounding": {
                "score": result.get("grounding_score"),
                "cited": result.get("grounding_cited", []),
                "notes": result.get("grounding_notes", []),
                "ungrounded": ungrounded,
            },
        }
        response["grounding"] = {
            "score": result.get("grounding_score"),
            "cited": result.get("grounding_cited", []),
            "notes": result.get("grounding_notes", []),
            "ungrounded": ungrounded,
        }
    return response


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# User-facing copy for a failed synthesis. Deliberately names the real cause
# (a provider quota / outage) and says it is retryable, because the alternative
# — a silent canned answer — looks like a successful grounded response and makes
# the product look broken rather than busy.
LLM_UNAVAILABLE_MESSAGE = (
    "The language model is temporarily unavailable — most often the free-tier "
    "token quota is used up for the day. Your question was not answered. "
    "Please retry in a few minutes."
)


def _llm_error_message(exc: Exception) -> str:
    if isinstance(exc, SynthesisUnavailable):
        return LLM_UNAVAILABLE_MESSAGE
    return f"Something went wrong while answering: {exc}"


def _resolve_history(history, conversation_id, owner=None, dosha_profile=None):
    """Load the stored thread, but only when the caller sent no history at all.

    The difference between ``None`` and ``[]`` is load-bearing here. ``None``
    means "I have no opinion, load whatever the thread holds"; ``[]`` means "this
    turn has no prior context". Only ``None`` consults the store, so a client that
    defaults an absent field to ``[]`` silently pins every turn to the first one —
    which is exactly what the frontend was doing, making multi-turn memory look
    implemented while it could never fire.

    Returns ``(history, dosha_profile)``; the stored profile is used only to fill
    a gap, never to override one the caller supplied.
    """
    if history is not None or not conversation_id:
        return history, dosha_profile
    store = _history_from_store(conversation_id, owner)
    return store["history"], dosha_profile or store["dosha_profile"]


def _history_from_store(conversation_id, owner=None):
    record = conversations.get_conversation(conversation_id, owner)
    if not record:
        return {"history": None, "dosha_profile": None}
    return {
        "history": [
            {"role": m["role"], "content": m["content"]}
            for m in record["messages"]
            if m.get("content")
        ],
        "dosha_profile": record.get("dosha_profile"),
    }


def _history_fingerprint(history: Optional[List[dict]]) -> str:
    """Short, stable digest of the conversation history used for synthesis.

    Two requests with the same query but different prior turns are different
    questions, so the history has to be part of the cache key. Hashing the last
    few turns (the same window the synthesis prompt actually includes) keeps
    the key short while staying correct.

    That window is `MAX_HISTORY_TURNS`, not a literal. It has to be the same
    value `_format_history` uses: if the prompt carried ten turns while this
    hashed six, a change confined to turn seven would leave the key unchanged
    and a stale answer could be served.
    """
    if not history:
        return "none"
    parts = []
    for m in history[-MAX_HISTORY_TURNS:]:
        role = m.get("role", "user")
        content = " ".join((m.get("content") or "").strip().split())
        parts.append(f"{role}:{content[:1200]}")
    blob = "\n".join(parts).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:16]


def _cache_scope(dosha_profile: Optional[str]) -> str:
    """Namespace the shared cache so a dosha-shaped answer is never handed to
    a user who has no dosha, or vice versa. Once accounts land, this becomes
    the authenticated user id, and any request touching memory or documents
    bypasses the cache entirely.
    """
    return f"dosha:{(dosha_profile or '').strip().lower()}" if dosha_profile else "shared"


def _suggest_questions(result) -> list:
    if (
        result.get("is_emergency")
        or result.get("is_out_of_scope")
        or result.get("is_clarification")
        or result.get("is_direct_answer")
    ):
        return []
    rc = result.get("resolved_chapter") or {}
    meta = rc.get("meta", {}) or {}
    condition = meta.get("traditional_condition") or meta.get("category_tag")
    herbs = result.get("herbs_found", [])
    dosha = result.get("dosha")

    out = []
    if herbs:
        out.append(f"How should {herbs[0].title()} be taken — dose and preparation?")
    if condition:
        out.append(f"What diet and habits suit {condition}?")
    if dosha:
        out.append(f"Which foods should be avoided on a {dosha} pattern?")
    if condition:
        out.append(f"What are the classical causes of {condition}?")
    out.append("What should I avoid while treating this?")
    return list(dict.fromkeys(out))[:3]


def _attach_summaries(resp, query, result, lang: Optional[str] = None):
    resp["suggestions"] = _suggest_questions(result)
    # A refusal must not be run through the summariser: that would re-ask the
    # LLM to summarise our own fixed text, and could soften a firm refusal.
    if result.get("final_answer") and not (
        result["is_emergency"] or result.get("is_out_of_scope")
    ):
        try:
            resp["summary"] = build_summary(query, resp["answer"], result, lang=lang or "en")
        except Exception as e:  # noqa: BLE001
            print(f"[main] summary failed ({e})")
    return resp


def _resolved_label(result) -> Optional[str]:
    rc = result.get("resolved_chapter") or {}
    meta = rc.get("meta")
    if not meta:
        return None
    return f"{meta.get('sthana')}/{meta.get('chapter')}"


def _chunks(text: str, size: int = 60):
    for i in range(0, len(text), size):
        yield text[i : i + size]


def _run_graph_collect(state):
    """Drive the graph via its stream so we can capture per-node latency + tokens."""
    merged = {}
    node_times = []
    usage = _TokenUsage()
    prev = time.time()
    for mode, payload in charaka_agent.stream(
        state,
        config=_graph_config(usage),
        stream_mode=["updates", "messages"],
    ):
        if mode == "updates":
            node = next(iter(payload))
            merged.update(payload[node])
            now = time.time()
            node_times.append([node, round((now - prev) * 1000), 0])
            prev = now
    if node_times:
        node_times[-1][2] = usage.completion
    print(
        f"[main] llm usage: {usage.calls} calls, "
        f"{usage.prompt} prompt + {usage.completion} completion tokens"
    )
    return merged, node_times, usage.completion, usage.prompt


async def _event_stream(
    query: str, history: Optional[List[dict]], conversation_id: Optional[str],
    dosha_profile: Optional[str], lang: Optional[str] = None,
    doc_session: Optional[str] = None,
    owner: Optional[str] = None,
    request: Optional[Request] = None,
    regenerate: bool = False,
):
    queue: asyncio.Queue = asyncio.Queue()
    # Set when the browser goes away (Stop button, tab close, network drop).
    # The worker thread polls it so an abandoned request stops calling the LLM
    # instead of burning a Groq slot and tokens on an answer nobody will read.
    abandoned = threading.Event()
    # Set separately by the deadline watchdog so the worker can tell "the client
    # left, nobody is listening" (exit silently) from "we ran too long" (tell the
    # user, and tell them to retry).
    deadline_hit = threading.Event()

    history, dosha_profile = _resolve_history(
        history, conversation_id, owner, dosha_profile
    )

    # Cacheability must key on everything the answer actually depends on: the
    # query, the dosha profile, the owning user, AND the conversation history
    # (which is embedded in the synthesis prompt). Keying on the query alone
    # would serve an answer written against turn 1 to someone asking in turn 5.
    # Hashing the history means a genuine repeat — the Retry button, or a
    # regenerate of the same turn — now hits instead of paying for the LLM
    # again. It is also per-user scoped, so no answer crosses accounts.
    cacheable = not doc_session
    cache_key = (
        cache.LRUCache.key_for(
            query,
            dosha_profile,
            scope=(
                f"{_cache_scope(dosha_profile)}|u={owner or 'shared'}"
                f"|h={_history_fingerprint(history)}|c={_CORPUS_VERSION}"
            ),
        )
        if cacheable
        else None
    )
    if cache_key:
        cached = _QUERY_CACHE.get(cache_key)
        if cached:
            trace.write_trace(
                TRACES_DIR,
                query,
                [("cache", 0, 0)],
                0,
                0,
                cache_hit=True,
                dosha=dosha_profile,
            )
            yield _sse(
                "stage",
                {"node": "cache", "label": "Serving cached answer", "ms": 0},
            )
            for part in _chunks(cached.get("answer", "")):
                yield _sse("token", {"delta": part})
            hit = dict(cached)
            hit["cache_hit"] = True
            yield _sse("done", hit)
            return

    state = {"query": query, "history": history or []}
    if dosha_profile:
        state["dosha_profile"] = dosha_profile
    if doc_session:
        state["doc_session"] = doc_session

    # Owned here rather than inside run() because the SSE consumer below reads the
    # totals when the worker publishes "done". The worker mutates it; the consumer
    # only reads, and only after that hand-off, so no lock is needed.
    usage = _TokenUsage()

    def run():
        merged = {}
        synthesize_seen = False
        acquired = _GATE.acquire()
        if not acquired:
            queue.put_nowait(
                (
                    "error",
                    {
                        "message": "the assistant is busy — too many questions at once, please retry",
                        "retryable": True,
                    },
                )
            )
            queue.put_nowait(("done", {}))
            return
        try:
            # The gate can block for up to CHARAKA_LLM_QUEUE_TIMEOUT, so a request
            # may already be past its deadline by the time a slot frees up.
            if abandoned.is_set():
                _report_abandon()
                return
            for mode, payload in charaka_agent.stream(
                state,
                config=_graph_config(usage),
                stream_mode=["updates", "messages"],
            ):
                if abandoned.is_set():
                    _report_abandon()
                    return
                if mode == "updates":
                    node = next(iter(payload))
                    merged.update(payload[node])
                    queue.put_nowait(("stage", node))
                else:
                    chunk, meta = payload
                    if meta.get("langgraph_node") == "synthesize":
                        if not synthesize_seen:
                            synthesize_seen = True
                            queue.put_nowait(("stage", "synthesize"))
                        text = getattr(chunk, "content", "")
                        if isinstance(text, str) and text:
                            queue.put_nowait(("token", text))
        except Exception as e:  # noqa: BLE001
            queue.put_nowait(
                (
                    "error",
                    {
                        "message": _llm_error_message(e),
                        "retryable": isinstance(e, SynthesisUnavailable),
                    },
                )
            )
        finally:
            _GATE.release()
            print(
                f"[main] llm usage: {usage.calls} calls, "
                f"{usage.prompt} prompt + {usage.completion} completion tokens"
            )
            queue.put_nowait(("done", merged))

    def _report_abandon() -> None:
        if deadline_hit.is_set():
            print(f"[main] request exceeded {_REQUEST_DEADLINE_S}s deadline")
            queue.put_nowait(
                (
                    "error",
                    {
                        "message": (
                            "this question took longer than expected and was stopped "
                            "— please retry"
                        ),
                        "retryable": True,
                    },
                )
            )
        else:
            print("[main] client disconnected mid-stream — abandoning run")

    t_start = time.time()
    threading.Thread(target=run, daemon=True).start()

    # Watch for the client going away for the whole life of the stream. Without
    # this, closing the tab mid-answer leaves the worker calling Groq to
    # completion, which spends tokens and holds one of only two LLM slots.
    async def _watch_disconnect() -> None:
        while not abandoned.is_set():
            if await request.is_disconnected():
                abandoned.set()
                return
            await asyncio.sleep(0.5)

    # Server-side wall clock for the run. The worker thread polls `abandoned` and
    # stops calling the LLM once it trips, so the deadline frees the Groq slot
    # instead of merely hiding the result. Reuses the existing Event rather than
    # wrapping the sync generator in asyncio.wait_for, which the worker thread
    # would not observe.
    async def _watch_deadline() -> None:
        remaining = _REQUEST_DEADLINE_S - (time.time() - t_start)
        if remaining > 0:
            await asyncio.sleep(remaining)
        if not abandoned.is_set():
            deadline_hit.set()
            abandoned.set()

    watcher = (
        asyncio.create_task(_watch_disconnect()) if request is not None else None
    )
    deadline_watcher = asyncio.create_task(_watch_deadline())

    t0 = time.time()
    prev = t0
    node_times = []
    try:
        while True:
            kind, payload = await queue.get()
            now = time.time()
            if kind == "stage":
                ms = round((now - prev) * 1000)
                prev = now
                node_times.append((payload, ms, 0))
                yield _sse(
                    "stage",
                    {
                        "node": payload,
                        "label": STAGE_LABELS.get(payload, payload.replace("_", " ")),
                        "ms": ms,
                    },
                )
            elif kind == "token":
                yield _sse("token", {"delta": payload})
            elif kind == "error":
                if isinstance(payload, dict):
                    yield _sse("error", payload)
                else:
                    yield _sse("error", {"message": payload, "retryable": False})
                break
            elif kind == "done":
                latency = round((now - t0) * 1000)
                resp = build_response(payload, latency_ms=latency)
                resp["suggestions"] = _suggest_questions(payload)
                if payload.get("final_answer"):
                    # Regenerate overwrites the previous attempt in place. If
                    # the stored shape is not a user/assistant pair we fall
                    # back to appending, so a turn is never lost.
                    replaced = regenerate and conversations.replace_last_turn(
                        conversation_id, resp, owner
                    )
                    if not replaced:
                        conv_id, conv_title = conversations.save_turn(
                            conversation_id, query, resp, owner
                        )
                        resp["conversation_id"] = conv_id
                        resp["conversation_title"] = conv_title
                        conversation_id = conv_id
                    else:
                        record = conversations.get_conversation(
                            conversation_id, owner
                        )
                        resp["conversation_id"] = conversation_id
                        resp["conversation_title"] = (
                            record.get("title") if record else None
                        )
                    resp["regenerated"] = bool(replaced)
                resp["cache_hit"] = False
                if node_times:
                    # Real completion tokens, read from the provider by the
                    # worker's callback handler. The worker publishes "done"
                    # after its last LLM call, so this read is final.
                    node_times[-1] = (
                        node_times[-1][0],
                        node_times[-1][1],
                        usage.completion,
                    )
                trace.write_trace(
                    TRACES_DIR,
                    query,
                    node_times,
                    usage.completion,
                    latency,
                    prompt_tokens=usage.prompt,
                    dosha=payload.get("dosha"),
                    resolved_chapter=_resolved_label(payload),
                )
                # Build the summary BEFORE persisting the turn, so the stored
                # assistant message includes it and a reloaded conversation does
                # not depend on regenerating. The `done` event is still emitted
                # first, so the user sees the answer immediately.
                summary = None
                if payload.get("final_answer") and not (
                    payload.get("is_emergency")
                    or payload.get("is_out_of_scope")
                    # Summarising "Namaste, ask me anything" would spend a full
                    # synthesis-class call to condense a canned greeting.
                    or payload.get("is_direct_answer")
                ):
                    try:
                        if _GATE.acquire():
                            try:
                                summary = build_summary(
                                    query, resp["answer"], payload, lang=lang or "en"
                                )
                            finally:
                                _GATE.release()
                    except Exception as e:  # noqa: BLE001
                        print(f"[main] summary failed ({e})")
                        summary = None
                if summary:
                    resp["summary"] = summary
                if payload.get("final_answer"):
                    # Append-only store: re-save with the summary would duplicate
                    # the turn, so the summary is patched onto the stored message
                    # instead.
                    conversations.patch_last_assistant(
                        conversation_id, {"summary": summary}, owner
                    )
                if cache_key and payload.get("final_answer") and not payload.get(
                    "is_emergency"
                ):
                    _QUERY_CACHE.set(cache_key, resp)
                yield _sse("done", resp)
                if summary:
                    yield _sse("summary", {"summary": summary})
                break
    finally:
        if watcher is not None:
            watcher.cancel()
        deadline_watcher.cancel()


@app.post("/ask", dependencies=[Depends(guard_ask)])
def ask(req: AskRequest, request: Request):
    owner = _owner(request)
    # Resolve the stored thread the same way the streaming path does. This
    # endpoint used `req.history or []` directly, so a caller that sent only a
    # conversation_id got first-turn behaviour while the browser got real
    # multi-turn — the two disagreed about the same feature.
    history, dosha_profile = _resolve_history(
        req.history, req.conversation_id, owner, req.dosha_profile
    )
    state = {"query": req.query, "history": history or []}
    if dosha_profile:
        state["dosha_profile"] = dosha_profile
    if req.doc_session:
        state["doc_session"] = _doc_scope(owner, req.doc_session)

    # Same key composition as the streaming path: query + dosha + owner +
    # history fingerprint. See _event_stream for why history belongs in the key.
    # It is keyed on the *resolved* history, so a thread turn cannot be answered
    # from a cache entry built for a different point in the conversation.
    cache_key = (
        cache.LRUCache.key_for(
            req.query,
            dosha_profile,
            scope=(
                f"{_cache_scope(dosha_profile)}|u={owner}"
                f"|h={_history_fingerprint(history)}|c={_CORPUS_VERSION}"
            ),
        )
        if not req.doc_session
        else None
    )
    if cache_key:
        cached = _QUERY_CACHE.get(cache_key)
        if cached:
            resp = dict(cached)
            resp["cache_hit"] = True
            trace.write_trace(
                TRACES_DIR,
                req.query,
                [("cache", 0, 0)],
                0,
                0,
                cache_hit=True,
                dosha=req.dosha_profile,
            )
            return resp

    t0 = time.time()
    if not _GATE.acquire():
        raise HTTPException(
            status_code=503,
            detail="the assistant is busy — too many questions at once, retry shortly",
            headers={"Retry-After": "3"},
        )
    try:
        result, node_times, token_count, prompt_tokens = _run_graph_collect(state)
    except SynthesisUnavailable as e:
        # Surface as a retryable 503 rather than an opaque 500. Nothing was
        # persisted and nothing was cached, so the client can safely re-ask.
        print(f"[main] synthesis unavailable: {e}")
        raise HTTPException(
            status_code=503,
            detail=LLM_UNAVAILABLE_MESSAGE,
            headers={"Retry-After": "30"},
        )
    finally:
        _GATE.release()
    latency = round((time.time() - t0) * 1000)
    resp = build_response(result, latency_ms=latency)
    resp["suggestions"] = _suggest_questions(result)
    if result.get("final_answer") and not (
        result.get("is_emergency")
        or result.get("is_out_of_scope")
        or result.get("is_direct_answer")
    ):
        if _GATE.acquire():
            try:
                resp = _attach_summaries(resp, req.query, result, lang=req.lang)
            finally:
                _GATE.release()
        else:
            resp["suggestions"] = _suggest_questions(result)
    resp["cache_hit"] = False
    if cache_key and result.get("final_answer") and not result.get("is_emergency"):
        _QUERY_CACHE.set(cache_key, resp)
    trace.write_trace(
        TRACES_DIR,
        req.query,
        node_times,
        token_count,
        latency,
        prompt_tokens=prompt_tokens,
        dosha=result.get("dosha"),
        resolved_chapter=_resolved_label(result),
    )
    return resp


@app.post("/ask/stream", dependencies=[Depends(guard_ask)])
async def ask_stream(req: AskRequest, request: Request):
    return StreamingResponse(
        _event_stream(
            req.query, req.history, req.conversation_id, req.dosha_profile,
            lang=req.lang,
            doc_session=(
                _doc_scope(_owner(request), req.doc_session)
                if req.doc_session
                else None
            ),
            owner=_owner(request),
            request=request,
            regenerate=req.regenerate,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/auth/register")
def register(req: RegisterRequest):
    try:
        user = auth.create_user(req.email, req.password, req.name)
    except auth.AuthError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    return {"token": auth.issue_token(user["id"]), "user": user}


@app.post("/auth/login")
def login(req: LoginRequest):
    try:
        user = auth.authenticate(req.email, req.password)
    except auth.AuthError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    return {"token": auth.issue_token(user["id"]), "user": user}


@app.post("/auth/logout")
def logout(authorization: Optional[str] = Header(default=None)):
    return {"ok": auth.revoke_token(_bearer_token(authorization))}


@app.get("/auth/me")
def me(user: Optional[dict] = Depends(current_user)):
    return {"user": user, "auth_required": AUTH_REQUIRED}


@app.get("/auth/config")
def auth_config():
    """Public, non-identifying. Tells the client whether to show the sign-in
    screen and how many accounts already exist, so the first visitor knows to
    register rather than being told their password is wrong."""
    return {"auth_required": AUTH_REQUIRED, "needs_registration": auth.count_users() == 0}


@app.get("/conversations", dependencies=[Depends(guard_private)])
def list_conversations(request: Request):
    return {"conversations": conversations.list_conversations(_owner(request))}


@app.get("/conversations/{conversation_id}", dependencies=[Depends(guard_private)])
def get_conversation(conversation_id: str, request: Request):
    record = conversations.get_conversation(conversation_id, _owner(request))
    if record is None:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "conversation": record}


@app.delete(
    "/conversations/{conversation_id}", dependencies=[Depends(guard_private)]
)
def delete_conversation(conversation_id: str, request: Request):
    return {"ok": conversations.delete_conversation(conversation_id, _owner(request))}


def _doc_scope(owner: Optional[str], session_id: str) -> str:
    """Namespace a client-supplied document session id by its owner.

    The session id arrives from the browser, so without this any signed-in user
    could pass someone else's id and read or delete their uploaded documents.
    """
    safe = "".join(ch for ch in (session_id or "") if ch.isalnum() or ch in "-_")[:64]
    return f"u_{owner or 'shared'}_{safe or 'default'}"


@app.post("/documents/upload", dependencies=[Depends(guard_private)])
async def upload_document(
    request: Request,
    session_id: str = Form(...),
    file: UploadFile = File(...),
):
    from app import documents

    data = await file.read()
    try:
        result = documents.upload(
            _doc_scope(_owner(request), session_id),
            file.filename or "document.txt",
            data,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, **result}


@app.get("/documents/{session_id}", dependencies=[Depends(guard_private)])
def list_documents(session_id: str, request: Request):
    from app import documents

    return {
        "ok": True,
        "documents": documents.list_uploads(_doc_scope(_owner(request), session_id)),
    }


@app.delete("/documents/{session_id}", dependencies=[Depends(guard_private)])
def delete_documents(session_id: str, request: Request):
    from app import documents

    return {
        "ok": True,
        "removed": documents.remove(_doc_scope(_owner(request), session_id)),
    }


@app.get("/healthz")
def healthz():
    """Liveness plus index freshness.

    The heartbeat workflow polls this endpoint to keep the free Space awake, so
    it must stay cheap and must never fail because the index is stale -- a stale
    index is reported, not fatal. An unhealthy answer would also silently stop
    the keep-alive, so ``ok`` tracks liveness only.
    """
    fresh = {}
    try:
        from app.chunking import index_freshness
        from app.nodes.retriever import collection

        fresh = index_freshness(collection)
    except Exception as exc:  # noqa: BLE001 - a health check must not raise
        fresh = {"status": "unknown", "detail": f"freshness check failed: {exc}"}

    if fresh.get("status") == "stale":
        print(f"[healthz] STALE INDEX: {fresh.get('detail')}")
    return {
        "ok": True,
        "app": "charaka-ai",
        "ts": int(time.time()),
        "index": fresh,
    }


@app.get("/corpus/sthanas")
def corpus_sthanas():
    chapters_by_sthana = {}
    for v in _CORPUS:
        key = v["sthana"]
        bucket = chapters_by_sthana.setdefault(
            key, {}
        )
        ch = bucket.setdefault(
            v["chapter"],
            {
                "chapter": v["chapter"],
                "verse_count": 0,
                "condition": v.get("traditional_condition"),
                "category": v.get("category_tag"),
            },
        )
        ch["verse_count"] += 1

    sthanas = []
    for sthana in STHANA_ORDER:
        if sthana not in chapters_by_sthana:
            continue
        chapters = sorted(
            chapters_by_sthana[sthana].values(), key=lambda c: c["chapter"]
        )
        sthanas.append(
            {
                "sthana": sthana,
                "title": STHANA_TITLES.get(sthana, sthana),
                "chapters": chapters,
                "verse_count": sum(c["verse_count"] for c in chapters),
            }
        )
    return {"sthanas": sthanas, "total_verses": len(_CORPUS)}


@app.get("/corpus/{sthana}/{chapter}")
def corpus_verses(sthana: str, chapter: int):
    ch = int(chapter)
    verses = [
        {
            "verse_id": v["verse_id"],
            "text": v["text_english"],
            "sanskrit": v.get("text_sanskrit"),
            "condition": v.get("traditional_condition"),
            "category": v.get("category_tag"),
            "herbs": [],
        }
        for v in _CORPUS
        if v["sthana"] == sthana and v["chapter"] == ch
    ]
    return {"ok": bool(verses), "sthana": sthana, "chapter": ch, "verses": verses}


class CorpusSearchRequest(BaseModel):
    query: str
    limit: int = 8


class HindiSummaryRequest(BaseModel):
    # Length caps matter here: the fields are caller-supplied and forwarded to
    # the LLM, so an unbounded query would let anyone drain the daily TPM
    # budget on this endpoint alone.
    query: str = Field(..., max_length=500)
    answer: str = Field(..., max_length=4000)
    retrieved: List[dict] = Field(default_factory=list, max_length=6)
    is_emergency: bool = False
    is_clarification: bool = False


@app.post("/summary/hindi", dependencies=[Depends(guard_private)])
def summary_hindi(req: HindiSummaryRequest):
    """Generate the Hindi summary on demand.

    The card's EN/HI toggle used to depend on the Hindi block being generated
    for every answer. This endpoint generates it the first time it is actually
    requested, which removes ~2.8K tokens from every English question.
    """
    if not _GATE.acquire():
        raise HTTPException(
            status_code=503,
            detail="the assistant is busy — retry in a moment",
            headers={"Retry-After": "3"},
        )
    try:
        result = build_hindi_summary(
            req.query,
            req.answer,
            {
                "retrieved": req.retrieved,
                "is_emergency": req.is_emergency,
                "is_clarification": req.is_clarification,
            },
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"hindi summary failed: {e}")
    finally:
        _GATE.release()
    return {"ok": result is not None, "hindi": result}


@app.post("/corpus/search")
def corpus_search(req: CorpusSearchRequest):
    from app.nodes.retriever import search_verses

    limit = max(1, min(req.limit, 25))
    return {"query": req.query, "results": search_verses(req.query, limit=limit)}


@app.post("/feedback", dependencies=[Depends(guard_private)])
def feedback(req: FeedbackRequest):
    FEEDBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "message_id": req.message_id,
        "query": req.query,
        "rating": req.rating,
        "dosha": req.dosha,
        "category_tag": req.category_tag,
        "chapter": req.chapter,
        "answer": req.answer,
        "trace": req.trace,
    }
    with FEEDBACK_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True}


@app.get("/stats", dependencies=[Depends(guard_admin)])
def get_stats():
    data = _FEEDBACK_STATS.snapshot()
    data["cache"] = _QUERY_CACHE.stats()
    data["llm_gate"] = _GATE.stats()
    return data


@app.get("/traces", dependencies=[Depends(guard_admin)])
def list_traces(limit: int = 50):
    limit = max(1, min(limit, 200))
    return {"traces": trace.list_traces(TRACES_DIR, limit)}


@app.get("/traces/{run_id}", dependencies=[Depends(guard_admin)])
def get_trace(run_id: str):
    record = trace.get_trace(TRACES_DIR, run_id)
    if record is None:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "trace": record}


class EvalRunRequest(BaseModel):
    corner: bool = True
    mode: Literal["retrieval", "full"] = "retrieval"


def _public_eval_row(row: dict) -> dict:
    return {
        "eval_id": row["eval_id"],
        "corner": row["corner"],
        "known_gap": row["known_gap"],
        "question": row["question"],
        "expected": row["expected"],
        "resolved": row["resolved"],
        "confidence": row["confidence"],
        "resolved_hit": row["resolved_hit"],
        "top_n_hit": row["top_n_hit"],
        "emergency": row["emergency"],
        "herbs_found": len(row["herbs_found"]),
        "safety_flags": len(row["safety_flags"]),
    }


async def _eval_event_stream(corner: bool, mode: str):
    from app.eval_suite import load_eval_items, run_question, summarize

    queue: asyncio.Queue = asyncio.Queue()
    items = load_eval_items(corner=corner)

    def run():
        rows = []
        try:
            for i, item in enumerate(items):
                row = run_question(item, mode=mode)
                rows.append(row)
                queue.put_nowait(
                    (
                        "item",
                        {
                            "index": i + 1,
                            "total": len(items),
                            **_public_eval_row(row),
                        },
                    )
                )
                time.sleep(0.05)
            summary = summarize(rows)
            payload = {
                "summary": summary,
                "rows": [_public_eval_row(r) for r in rows],
            }
            try:
                EVAL_RESULTS.write_text(
                    json.dumps(payload, ensure_ascii=False),
                    encoding="utf-8",
                )
            except OSError:
                pass
            queue.put_nowait(("done", payload))
        except Exception as e:  # noqa: BLE001
            queue.put_nowait(("error", str(e)))

    threading.Thread(target=run, daemon=True).start()

    while True:
        kind, payload = await queue.get()
        yield _sse(kind, payload)
        if kind in ("done", "error"):
            break


@app.post("/eval/run", dependencies=[Depends(guard_admin)])
async def eval_run(req: EvalRunRequest):
    return StreamingResponse(
        _eval_event_stream(req.corner, req.mode),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/eval/last", dependencies=[Depends(guard_admin)])
def eval_last():
    if not EVAL_RESULTS.exists():
        return {"ok": False, "error": "no_runs"}
    try:
        return {"ok": True, **json.loads(EVAL_RESULTS.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "error": "unreadable"}


def _load_reference(name: str):
    with open(REFERENCE / name, encoding="utf-8") as f:
        return json.load(f)


@app.get("/herbs")
def herbs():
    herb_list = _load_reference("herbs.json")["herbs"]
    safety_list = _load_reference("herb_safety.json")
    botanicals = _load_reference("botanical_names.json")

    safety_by_key = {}
    for entry in safety_list:
        safety_by_key[entry["herb"]] = entry
        for alias in _load_reference("herbs.json").get("herbs", []):
            if alias["name"] != entry["herb"]:
                continue
            for a in alias.get("aliases", []):
                safety_by_key.setdefault(a, entry)

    catalog = []
    for h in herb_list:
        name = h["name"]
        entry = safety_by_key.get(name)
        if entry is None:
            for a in h.get("aliases", []):
                if a in safety_by_key:
                    entry = safety_by_key[a]
                    break
        if entry is None:
            entry = {}

        dosha_tags = []
        caution = (entry.get("dosha_caution") or "").lower()
        for d in ("vata", "pitta", "kapha"):
            if d in caution:
                dosha_tags.append(d.capitalize())

        catalog.append(
            {
                "name": name,
                "aliases": h.get("aliases", []),
                "botanical": botanicals.get(name),
                "dosha_tags": dosha_tags,
                "modern_source_verified": bool(entry.get("modern_source_verified")),
                "api_of_india_verified": bool(entry.get("api_of_india_verified")),
                "dosha_caution": entry.get("dosha_caution", ""),
                "contraindications": entry.get("contraindications", []),
                "interactions": entry.get("interactions", []),
                "pregnancy_flag": entry.get("pregnancy_flag", ""),
                "classical_source": entry.get("classical_source", ""),
                "modern_source": entry.get("modern_source", ""),
                "verification_note": entry.get("verification_note", ""),
            }
        )

    catalog.sort(key=lambda h: h["name"])
    return {"herbs": catalog, "count": len(catalog), "covered": len(safety_list)}


FRONTEND_DIST = BACKEND.parent / "frontend" / "dist"


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    """Serve the built SPA on the same origin as the API (Wave D deployment).

    Falls over to index.html for client-side routes; API routes registered
    earlier always take precedence over this catch-all.
    """
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="frontend build not present")
    try:
        candidate = (FRONTEND_DIST / full_path).resolve()
        candidate.relative_to(FRONTEND_DIST.resolve())
    except (ValueError, OSError):
        raise HTTPException(status_code=404, detail="not found")
    if full_path and candidate.is_file():
        ctype = (
            mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        )
        return FileResponse(candidate, media_type=ctype)
    return FileResponse(index, media_type="text/html")
