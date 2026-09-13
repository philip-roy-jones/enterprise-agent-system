"""Local staff passwords. Service enrollment and authorization remain separate."""

import re
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import HTTPException

from eas_server.security import token_hash

# OWASP Argon2id minimum; bounded inputs and persistent throttles precede hashing.
HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))


def email_address(value):
    if not isinstance(value, str) or len(value) > 254:
        raise ValueError("A valid email address is required")
    value = value.strip().casefold()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("A valid email address is required")
    return value


def password_value(value):
    if not isinstance(value, str) or not 15 <= len(value) <= 256:
        raise HTTPException(400, "Use a password between 15 and 256 characters")
    return value


class Accounts:
    def __init__(self, security):
        self.security, self.store = security, security.store
        with self.store.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS staff_accounts (
                    principal TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
                    password_hash TEXT, setup_hash TEXT UNIQUE, setup_expires REAL);
                CREATE TABLE IF NOT EXISTS login_limits (
                    key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL);
            """)

    def invite(self, principal_id, email):
        """Operator-only provisioning/reset; no public enrollment endpoint."""
        principal = self.security.get(principal_id)
        if principal.kind != "human":
            raise ValueError("Only staff can have password accounts")
        email = email_address(email)
        token = secrets.token_urlsafe(48)
        with self.store.db() as db:
            db.execute(
                "INSERT INTO staff_accounts VALUES(?,?,NULL,?,?) "
                "ON CONFLICT(principal) DO UPDATE SET email=excluded.email, "
                "setup_hash=excluded.setup_hash, setup_expires=excluded.setup_expires",
                (principal_id, email, token_hash(token), time.time() + 3600),
            )
        return token

    def throttle(self, email, peer):
        now = time.time()
        blocked = False
        with self.store.db() as db:
            db.execute("DELETE FROM login_limits WHERE expires<=?", (now,))
            for key, limit in (("email:" + email, 10), ("peer:" + peer, 100)):
                key = token_hash(key)
                row = db.execute("SELECT count FROM login_limits WHERE key=?", (key,)).fetchone()
                count = (row[0] if row else 0) + 1
                blocked |= count > limit
                db.execute(
                    "INSERT INTO login_limits VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET count=?",
                    (key, count, now + 900, count),
                )
        if blocked:
            raise HTTPException(429, "Too many sign-in attempts; try again in 15 minutes")

    def login(self, email, password, peer):
        try:
            email = email_address(email)
        except ValueError:
            email = "invalid"
        self.throttle(email, peer)
        if not isinstance(password, str) or len(password) > 256:
            raise HTTPException(401, "Email or password is incorrect")
        with self.store.db() as db:
            row = db.execute("SELECT * FROM staff_accounts WHERE email=?", (email,)).fetchone()
        try:
            HASHER.verify(row["password_hash"] if row and row["password_hash"] else DUMMY_HASH, password)
        except (VerificationError, InvalidHashError):
            raise HTTPException(401, "Email or password is incorrect") from None
        if not row or not row["password_hash"]:
            raise HTTPException(401, "Email or password is incorrect")
        principal = self.security.get(row["principal"])
        if principal.kind != "human":
            raise HTTPException(401, "Email or password is incorrect")
        # Bind the session to the current hash transactionally, so a concurrent
        # reset cannot let an already-running old-password check mint a session.
        with self.store.db() as db:
            current = db.execute(
                "SELECT password_hash FROM staff_accounts WHERE principal=?", (principal.id,)
            ).fetchone()
            if not current or current[0] != row["password_hash"]:
                raise HTTPException(401, "Email or password is incorrect")
            result = self.security.create_session(principal, db=db)
        return result

    def setup(self, token, email, password, peer):
        email = email_address(email)
        self.throttle(email, peer)
        if not isinstance(token, str) or not 20 <= len(token) <= 100:
            raise HTTPException(400, "Setup link is invalid or expired")
        password = password_value(password)
        with self.store.db() as db:
            row = db.execute(
                "SELECT principal FROM staff_accounts WHERE setup_hash=? AND email=? AND setup_expires>?",
                (token_hash(token), email, time.time()),
            ).fetchone()
        if not row or self.security.get(row[0]).kind != "human":
            raise HTTPException(400, "Setup link is invalid or expired")
        hashed = HASHER.hash(password)
        with self.store.db() as db:
            changed = db.execute(
                "UPDATE staff_accounts SET password_hash=?, setup_hash=NULL, setup_expires=NULL "
                "WHERE principal=? AND email=? AND setup_hash=? AND setup_expires>?",
                (hashed, row[0], email, token_hash(token), time.time()),
            ).rowcount
            if changed != 1:
                raise HTTPException(400, "Setup link is invalid or expired")
            db.execute("DELETE FROM security_sessions WHERE principal=?", (row[0],))
            db.execute("DELETE FROM login_limits WHERE key=?", (token_hash("email:" + email),))
        return {"ok": True}
