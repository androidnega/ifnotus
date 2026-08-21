from app.services.totp import new_secret, verify_code, _hotp
import time


def test_totp_roundtrip() -> None:
    secret = new_secret()
    code = _hotp(secret, int(time.time()) // 30)
    assert verify_code(secret, code)
    assert not verify_code(secret, "000000")
