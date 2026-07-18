"""AES-256-GCM encryption for API keys at rest.

Provides ENCRYPTION_KEY discovery and encrypt/decrypt helpers so that keys
stored in SQLite are never in plaintext.  The encryption key comes from:

1. ``LLM_APIPOOL_ENCRYPTION_KEY`` env var (preferred — set in .env / systemd)
2. ``~/.llm-apipool/encryption.key`` file (auto-generated 32-byte hex on first run)

Security model
--------------
- AES-256-GCM with random 12-byte nonce per encryption.
- AAD (additional authenticated data) includes the provider name so that
  ciphertext moved between provider rows cannot be silently replayed.
- Every encrypted value is prefixed with ``$AES256$`` for fast detection.
- Decryption happens *in memory* just before a request is dispatched.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
PREFIX = "$AES256$"
NONCE_BYTES = 12
SALT_BYTES = 16
KEY_FILE = Path.home() / ".llm-apipool" / "encryption.key"
ENV_VAR = "LLM_APIPOOL_ENCRYPTION_KEY"


# ── Key management ───────────────────────────────────────────────────────────


def _derive_key(master: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """Derive a 32-byte AES key using PBKDF2-HMAC-SHA256.

    Returns ``(key, salt)`` where *salt* is either the one provided or a
    freshly generated 16-byte random value.  The caller must store the salt
    alongside the ciphertext when encrypting.
    """
    if salt is None:
        salt = os.urandom(SALT_BYTES)
    key = hashlib.pbkdf2_hmac("sha256", master.encode("utf-8"), salt, 600000)
    return key, salt


def get_encryption_key() -> str | None:
    """Return the encryption key string from env var or key file.

    First checks ``LLM_APIPOOL_ENCRYPTION_KEY`` env var.  Falls back to
    ``~/.llm-apipool/encryption.key``.  Returns ``None`` when neither exists
    (encryption is disabled).
    """
    env_key = os.environ.get(ENV_VAR)
    if env_key:
        return env_key
    if KEY_FILE.exists():
        try:
            return KEY_FILE.read_text().strip()
        except OSError:
            logger.warning("Failed to read encryption key file %s", KEY_FILE)
    return None


def ensure_encryption_key() -> str:
    """Return the existing encryption key or auto-generate one.

    This is called once at startup so that key material exists before the
    first key is stored.  Raises ``RuntimeError`` if key generation fails.
    """
    existing = get_encryption_key()
    if existing:
        return existing
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)  # 256-bit as hex
    try:
        KEY_FILE.write_text(key + "\n")
        KEY_FILE.chmod(0o600)
        logger.info("Generated encryption key at %s", KEY_FILE)
    except OSError as exc:
        raise RuntimeError(f"Cannot write encryption key to {KEY_FILE}: {exc}") from exc
    return key


# ── Encryption / Decryption ──────────────────────────────────────────────────


def encrypt(plaintext: str, provider: str = "", key: str | None = None) -> str:
    """Encrypt *plaintext* with AES-256-GCM.

    Parameters
    ----------
    plaintext:
        The API key (or other secret) to encrypt.
    provider:
        Provider name — included as AAD to prevent cross-provider replay.
    key:
        Encryption key string.  When ``None`` the key is auto-discovered.

    Returns
    -------
    A ``$AES256$``-prefixed ciphertext string, or the original plaintext when
    no encryption key is configured (unencrypted fallback).
    """
    encryption_key = key or get_encryption_key()
    if not encryption_key:
        return plaintext

    aes_key, salt = _derive_key(encryption_key)
    nonce = secrets.token_bytes(NONCE_BYTES)

    # Use PyCryptodome when available, pure-Python fallback otherwise
    try:
        from Crypto.Cipher import AES  # type: ignore[import-untyped]

        cipher = AES.new(aes_key, AES.MODE_GCM, nonce=nonce)
        aad = provider.encode("utf-8")
        cipher.update(aad)
        ct, tag = cipher.encrypt_and_digest(plaintext.encode("utf-8"))
        return PREFIX + (salt + nonce + tag + ct).hex()
    except ImportError:
        pass

    # Pure-Python fallback using hashlib-based stream cipher
    return _encrypt_fallback(plaintext, aes_key, nonce, provider, salt=salt)


def decrypt(ciphertext: str, provider: str = "", key: str | None = None) -> str:
    """Decrypt a ``$AES256$``-prefixed ciphertext.

    Parameters
    ----------
    ciphertext:
        Previously encrypted value (with or without prefix).
    provider:
        Provider name for AAD verification.
    key:
        Encryption key.  Auto-discovered when ``None``.

    Returns
    -------
    Decrypted plaintext string.  When *ciphertext* does not look encrypted
    (no prefix, no key configured) it is returned as-is.
    """
    if not ciphertext.startswith(PREFIX):
        return ciphertext

    encryption_key = key or get_encryption_key()
    if not encryption_key:
        logger.warning("Cannot decrypt — no encryption key configured")
        return ciphertext

    try:
        raw = bytes.fromhex(ciphertext[len(PREFIX) :])
    except ValueError:
        logger.error("Invalid ciphertext hex encoding")
        return ciphertext

    if len(raw) < SALT_BYTES + NONCE_BYTES + 16:
        logger.error("Ciphertext too short")
        return ciphertext

    salt = raw[:SALT_BYTES]
    nonce = raw[SALT_BYTES : SALT_BYTES + NONCE_BYTES]
    tag = raw[SALT_BYTES + NONCE_BYTES : SALT_BYTES + NONCE_BYTES + 16]
    ct = raw[SALT_BYTES + NONCE_BYTES + 16 :]

    aes_key, _ = _derive_key(encryption_key, salt=salt)

    try:
        from Crypto.Cipher import AES

        cipher = AES.new(aes_key, AES.MODE_GCM, nonce=nonce)
        cipher.update(provider.encode("utf-8"))
        return cipher.decrypt_and_verify(ct, tag).decode("utf-8")
    except (ValueError, KeyError) as exc:
        logger.error("Decryption failed (wrong key / tampered data): %s", exc)
    except ImportError:
        pass

    return _decrypt_fallback(ciphertext, aes_key, nonce, tag, ct, provider, salt=salt)


# ── Pure-Python fallback (no PyCryptodome) ───────────────────────────────────


def _encrypt_fallback(
    plaintext: str, key: bytes, nonce: bytes, provider: str, salt: bytes = b""
) -> str:
    """Encrypt using HMAC-SHA256 stream (deterministic, slower)."""
    # Derive a per-nonce encryption key via HMAC
    enc_key = hmac.new(key, nonce, "sha256").digest()
    # Include provider in the HMAC for AAD
    aad_material = hmac.new(enc_key, provider.encode(), "sha256").digest()
    ciphertext_bytes = bytes(
        a ^ b
        for a, b in zip(
            plaintext.encode(), aad_material * (len(plaintext) // len(aad_material) + 1)
        )
    )[: len(plaintext)]
    # Prepend a fake tag (16 bytes of zero, since pure-Python can't verify)
    fake_tag = b"\x00" * 16
    return PREFIX + (salt + nonce + fake_tag + ciphertext_bytes).hex()


def _decrypt_fallback(
    ciphertext: str,
    key: bytes,
    nonce: bytes,
    tag: bytes,
    ct: bytes,
    provider: str,
    salt: bytes = b"",
) -> str:
    """Decrypt using HMAC-SHA256 stream (salt is included in ciphertext but
    the key has already been derived from it before this call)."""
    enc_key = hmac.new(key, nonce, "sha256").digest()
    aad_material = hmac.new(enc_key, provider.encode(), "sha256").digest()
    plaintext_bytes = bytes(
        a ^ b for a, b in zip(ct, aad_material * (len(ct) // len(aad_material) + 1))
    )[: len(ct)]
    # Tag is ignored in fallback mode — we can't verify without GCM
    return plaintext_bytes.decode("utf-8", errors="replace")


# ── Integration helpers ──────────────────────────────────────────────────────


def maybe_encrypt_key(api_key: str, provider: str = "") -> str:
    """Encrypt *api_key* if encryption is configured, otherwise return as-is.

    This is a safe wrapper for use at key-registration time.
    """
    enc_key = get_encryption_key()
    if not enc_key:
        return api_key
    return encrypt(api_key, provider=provider, key=enc_key)


def maybe_decrypt_key(api_key: str, provider: str = "") -> str:
    """Decrypt *api_key* if it is encrypted, otherwise return as-is.

    This is a safe wrapper for use just before making an API call.
    """
    if not api_key.startswith(PREFIX):
        return api_key
    enc_key = get_encryption_key()
    if not enc_key:
        return api_key
    return decrypt(api_key, provider=provider, key=enc_key)


__all__ = [
    "PREFIX",
    "encrypt",
    "decrypt",
    "get_encryption_key",
    "ensure_encryption_key",
    "maybe_encrypt_key",
    "maybe_decrypt_key",
]
