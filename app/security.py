"""Security helpers: hashing, masking, redaction, request authentication."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

_PBKDF2_ITERATIONS = 120_000


def hash_cnic(cnic_digits: str, pepper: str) -> str:
    """HMAC-SHA256 of the 13-digit CNIC. The raw CNIC is never stored."""
    return hmac.new(pepper.encode(), cnic_digits.encode(), hashlib.sha256).hexdigest()


def mask_cnic(cnic_digits: str) -> str:
    return f"*****-*******-{cnic_digits[-1]}"


def hash_pin(pin: str, salt_hex: str | None = None) -> tuple[str, str]:
    """PBKDF2 hash of a PIN. Returns (hash_hex, salt_hex)."""
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, _PBKDF2_ITERATIONS)
    return digest.hex(), salt.hex()


def verify_pin(pin: str, salt_hex: str, hash_hex: str) -> bool:
    candidate, _ = hash_pin(pin, salt_hex)
    return hmac.compare_digest(candidate, hash_hex)


def is_weak_pin(pin: str) -> bool:
    if len(pin) != 4 or not pin.isdigit():
        return True
    if len(set(pin)) == 1:
        return True
    digits = [int(c) for c in pin]
    steps = {digits[i + 1] - digits[i] for i in range(3)}
    return steps == {1} or steps == {-1}


_LONG_DIGITS = re.compile(r"(?:\d[\s-]?){9,}")


def redact_digits(text: str) -> str:
    """Replace runs of 9+ digits (CNIC, card numbers) with a marker."""
    return _LONG_DIGITS.sub("[REDACTED]", text)


def api_key_ok(provided: str | None, expected: str) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


def verify_twilio_signature(token: str, url: str, params: dict[str, str], signature: str) -> bool:
    payload = url + "".join(k + str(params[k]) for k in sorted(params))
    expected = base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, signature or "")
