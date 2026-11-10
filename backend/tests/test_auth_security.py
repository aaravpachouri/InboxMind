from gmail_agent.auth_security import (
    create_one_time_token,
    hash_one_time_token,
    hash_password,
    verify_password,
)


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")
    assert first != second
    assert verify_password("correct horse battery staple", first)
    assert not verify_password("wrong password", first)


def test_password_rejects_weak_or_oversized_input():
    import pytest
    with pytest.raises(ValueError):
        hash_password("short")
    with pytest.raises(ValueError):
        hash_password("x" * 1025)


def test_malformed_password_hash_fails_closed():
    assert not verify_password("anything", "plain-text-password")
    assert not verify_password("anything", "pbkdf2_sha256$1$bad$bad")


def test_one_time_token_is_only_persisted_as_digest():
    token, digest = create_one_time_token()
    assert token
    assert digest == hash_one_time_token(token)
    assert token.encode("ascii") not in digest
