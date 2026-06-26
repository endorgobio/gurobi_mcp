"""Unit tests for security primitives (T010): bcrypt, Fernet, JWT.

License-free — no Docker or Intelligence Hub access. Written before the
implementation per constitution Principle III.
"""

from __future__ import annotations

import time

import pytest
from cryptography.fernet import Fernet

from gurobimcp.auth import security


def test_password_hash_is_not_plaintext_and_verifies() -> None:
    hashed = security.hash_password("hunter2")
    assert hashed != "hunter2"
    assert "hunter2" not in hashed
    assert security.verify_password("hunter2", hashed) is True
    assert security.verify_password("wrong", hashed) is False


def test_password_hash_is_salted() -> None:
    assert security.hash_password("same") != security.hash_password("same")


def test_fernet_roundtrip_and_ciphertext_opaque() -> None:
    key = Fernet.generate_key().decode()
    token = security.encrypt_secret("my-gurobi-secret", key)
    assert token != "my-gurobi-secret"
    assert "my-gurobi-secret" not in token
    assert security.decrypt_secret(token, key) == "my-gurobi-secret"


def test_jwt_issue_and_verify_roundtrip() -> None:
    token = security.create_access_token(subject="42", secret="s3cret", ttl=60)
    assert security.decode_access_token(token, secret="s3cret") == "42"


def test_jwt_rejects_wrong_secret() -> None:
    token = security.create_access_token(subject="42", secret="right", ttl=60)
    with pytest.raises(security.TokenError):
        security.decode_access_token(token, secret="wrong")


def test_jwt_rejects_expired() -> None:
    token = security.create_access_token(subject="42", secret="s", ttl=1)
    time.sleep(1.2)
    with pytest.raises(security.TokenError):
        security.decode_access_token(token, secret="s")


def test_jwt_rejects_malformed() -> None:
    with pytest.raises(security.TokenError):
        security.decode_access_token("not-a-jwt", secret="s")
