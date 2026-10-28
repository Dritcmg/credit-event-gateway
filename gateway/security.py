import hashlib
import hmac
import re


class InvalidSignature(Exception):
    pass


def sign(secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode("ascii") + b"." + body
    return "v1=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify(
    secret: str, timestamp: str, signature: str, body: bytes, now: float, window: int
) -> None:
    if not re.fullmatch(r"[0-9]{1,12}", timestamp):
        raise InvalidSignature
    if abs(now - int(timestamp)) > window:
        raise InvalidSignature
    if not re.fullmatch(r"v1=[a-f0-9]{64}", signature):
        raise InvalidSignature
    if not hmac.compare_digest(sign(secret, timestamp, body), signature):
        raise InvalidSignature
