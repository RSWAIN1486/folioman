"""Encryption helpers for persisted, already-redacted AI chat text."""

from __future__ import annotations

from folioman_app.security.keys import get_fernet

_PREFIX = b"folioman-chat:"


def encrypt_chat_text(value: str) -> bytes:
    return get_fernet().encrypt(_PREFIX + value.encode())


def decrypt_chat_text(token: bytes) -> str:
    value = get_fernet().decrypt(bytes(token))
    if not value.startswith(_PREFIX):
        raise ValueError("Invalid chat ciphertext")
    return value[len(_PREFIX) :].decode()
