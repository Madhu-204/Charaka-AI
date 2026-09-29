"""Account registration, login and session tokens.

Deliberately dependency-free: password hashing uses stdlib PBKDF2-HMAC-SHA256
and sessions are opaque random tokens, so there is nothing to install and no
extra service to pay for. Sized for the handful of testers this app is built
for, not for millions of accounts.

Tokens are stored as SHA-256 digests, so a leaked database row cannot be
replayed as a live session.
"""

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DB_FILE = Path(os.getenv("CHARAKA_USERS_DB") or (BACKEND / "users.db"))

# PBKDF2 rounds. High enough to make offline cracking expensive, low enough to
# keep login responsive on a free-tier CPU.
_ITERATIONS = 200_000
_SALT_BYTES = 16
TOKEN_TTL_SECONDS = int(os.getenv("CHARAKA_SESSION_DAYS", "30")) * 86400

_lock = threading.Lock()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
MIN_PASSWORD = 8


class AuthError(Exception):
    """Raised for expected, user-facing auth failures."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_FILE), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db():
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            TEXT PRIMARY KEY,
                email         TEXT NOT NULL UNIQUE,
                name          TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL,
                created_at    TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id)"
        )


def hash_password(password: str, *, salt: bytes = None, iterations: int = None) -> str:
    """Return a self-describing PBKDF2 digest: algo$rounds$salt$hash."""
    salt = salt if salt is not None else os.urandom(_SALT_BYTES)
    rounds = iterations if iterations is not None else _ITERATIONS
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(rounds),
        )
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def create_user(email: str, password: str, name: str = "") -> dict:
    email = _normalise_email(email)
    name = (name or "").strip()[:80]

    if not EMAIL_RE.match(email):
        raise AuthError("Enter a valid email address.")
    if not password or len(password) < MIN_PASSWORD:
        raise AuthError(f"Password must be at least {MIN_PASSWORD} characters.")

    user_id = secrets.token_hex(8)
    with _lock, _connect() as conn:
        try:
            conn.execute(
                "INSERT INTO users (id, email, name, password_hash, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (user_id, email, name, hash_password(password), _now()),
            )
        except sqlite3.IntegrityError:
            raise AuthError(
                "An account with that email already exists. Try logging in.",
                status=409,
            )
    return get_user(user_id)


def get_user(user_id: str):
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, email, name, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str):
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, email, name, created_at FROM users WHERE email = ?",
            (_normalise_email(email),),
        ).fetchone()
    return dict(row) if row else None


def authenticate(email: str, password: str) -> dict:
    """Verify credentials and mint a session token.

    The same message is returned for an unknown email and a wrong password so
    the endpoint cannot be used to enumerate which addresses are registered.
    """
    email = _normalise_email(email)
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, email, name, created_at, password_hash FROM users"
            " WHERE email = ?",
            (email,),
        ).fetchone()

    # Always run the KDF so a missing account and a wrong password take
    # comparable time.
    stored = row["password_hash"] if row else hash_password("timing-equaliser")
    ok = verify_password(password or "", stored)

    if not row or not ok:
        raise AuthError("Email or password is incorrect.", status=401)

    return dict(id=row["id"], email=row["email"], name=row["name"], created_at=row["created_at"])


def issue_token(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at)"
            " VALUES (?, ?, ?, ?)",
            (_token_digest(token), user_id, _now(), now + TOKEN_TTL_SECONDS),
        )
    return token


def resolve_token(token: str):
    """Return the user for a live session token, or None."""
    if not token:
        return None
    now = int(time.time())
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT user_id FROM sessions WHERE token_hash = ? AND expires_at > ?",
            (_token_digest(token), now),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "DELETE FROM sessions WHERE expires_at <= ?", (now,)
        )
    return get_user(row["user_id"])


def revoke_token(token: str) -> bool:
    if not token:
        return False
    with _lock, _connect() as conn:
        cur = conn.execute(
            "DELETE FROM sessions WHERE token_hash = ?", (_token_digest(token),)
        )
        return cur.rowcount > 0


def count_users() -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


_init_db()
