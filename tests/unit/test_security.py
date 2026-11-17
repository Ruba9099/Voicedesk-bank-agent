import base64
import hashlib
import hmac

from app import security


def test_cnic_hash_is_deterministic_and_pepper_dependent():
    a = security.hash_cnic("3520212345671", "pepper-1")
    assert a == security.hash_cnic("3520212345671", "pepper-1")
    assert a != security.hash_cnic("3520212345671", "pepper-2")
    assert a != security.hash_cnic("3520212345672", "pepper-1")
    assert len(a) == 64


def test_mask_cnic_shows_only_last_digit():
    assert security.mask_cnic("3520212345671") == "*****-*******-1"


def test_pin_hash_roundtrip_and_wrong_pin():
    h, salt = security.hash_pin("4821")
    assert security.verify_pin("4821", salt, h)
    assert not security.verify_pin("4822", salt, h)


def test_pin_hash_uses_random_salt():
    h1, s1 = security.hash_pin("4821")
    h2, s2 = security.hash_pin("4821")
    assert s1 != s2 and h1 != h2


def test_weak_pins_are_rejected():
    for pin in ["0000", "1111", "1234", "4321", "2345", "9876", "0123"]:
        assert security.is_weak_pin(pin), pin


def test_non_numeric_or_wrong_length_pin_is_weak():
    for pin in ["12", "12345", "abcd", ""]:
        assert security.is_weak_pin(pin), pin


def test_strong_pin_accepted():
    assert not security.is_weak_pin("4821")
    assert not security.is_weak_pin("7390")


def test_redact_long_digit_runs_only():
    out = security.redact_digits("my card 4111111111111111 and cnic 35202-1234567-1 ok 1234")
    assert "4111111111111111" not in out
    assert "35202" not in out
    assert "1234567" not in out
    assert "1234" in out  # short runs are kept


def test_api_key_comparison():
    assert security.api_key_ok("secret", "secret")
    assert not security.api_key_ok("wrong", "secret")
    assert not security.api_key_ok(None, "secret")
    assert not security.api_key_ok("", "secret")


def test_twilio_signature_validation():
    token = "tok"
    url = "https://example.com/telephony/gather"
    params = {"CallSid": "CA1", "SpeechResult": "balance"}
    payload = url + "".join(k + params[k] for k in sorted(params))
    sig = base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()
    assert security.verify_twilio_signature(token, url, params, sig)
    assert not security.verify_twilio_signature(token, url, params, "bad")
    assert not security.verify_twilio_signature(token, url, {**params, "CallSid": "CA2"}, sig)
