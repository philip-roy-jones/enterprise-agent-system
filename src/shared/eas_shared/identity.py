"""Stable identifiers and value hashes shared by server and worker."""

import hashlib
import json
import uuid


def uid():
    return uuid.uuid4().hex


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()
