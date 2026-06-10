"""Unit-тесты HMAC-подписи webhook (E10-8 PR-A #198; ADR-0015 D3, У2 anti-replay)."""

from __future__ import annotations

import hashlib
import hmac

from api.webhooks.signing import compute_signature, signature_header, verify_signature

_PAYLOAD = b'{"event":"ticket.case_decided","ticket_id":"x"}'
_SECRET = "s" * 32
_TS = 1_700_000_000


def _expected(payload: bytes, secret: str, ts: int) -> str:
    """Независимый эталон алгоритма (ловит мутацию формата подписываемой строки)."""
    signed = f"{ts}.".encode() + payload
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def test_signature_matches_documented_algorithm() -> None:
    # Пиннит ТОЧНУЮ форму: HMAC-SHA256 над f"{timestamp}." + body (ADR-0015 D3).
    assert compute_signature(payload=_PAYLOAD, secret=_SECRET, timestamp=_TS) == _expected(
        _PAYLOAD, _SECRET, _TS
    )


def test_signature_is_deterministic() -> None:
    a = compute_signature(payload=_PAYLOAD, secret=_SECRET, timestamp=_TS)
    b = compute_signature(payload=_PAYLOAD, secret=_SECRET, timestamp=_TS)
    assert a == b


def test_timestamp_is_part_of_signature_anti_replay() -> None:
    # У2: timestamp ВКЛЮЧЁН в подпись → смена ts меняет подпись (иначе replay не защищён).
    base = compute_signature(payload=_PAYLOAD, secret=_SECRET, timestamp=_TS)
    other = compute_signature(payload=_PAYLOAD, secret=_SECRET, timestamp=_TS + 1)
    assert base != other


def test_secret_changes_signature() -> None:
    assert compute_signature(payload=_PAYLOAD, secret=_SECRET, timestamp=_TS) != compute_signature(
        payload=_PAYLOAD, secret="d" * 32, timestamp=_TS
    )


def test_body_changes_signature() -> None:
    assert compute_signature(payload=_PAYLOAD, secret=_SECRET, timestamp=_TS) != compute_signature(
        payload=_PAYLOAD + b" ", secret=_SECRET, timestamp=_TS
    )


def test_header_format() -> None:
    header = signature_header(payload=_PAYLOAD, secret=_SECRET, timestamp=_TS)
    digest = compute_signature(payload=_PAYLOAD, secret=_SECRET, timestamp=_TS)
    assert header == f"t={_TS},v1={digest}"


# --- verify_signature (inbound, PR-C) ---


def _header(payload: bytes, secret: str, ts: int) -> str:
    return signature_header(payload=payload, secret=secret, timestamp=ts)


def test_verify_accepts_valid_signature_within_tolerance() -> None:
    header = _header(_PAYLOAD, _SECRET, _TS)
    assert (
        verify_signature(
            payload=_PAYLOAD, secret=_SECRET, header=header, now=_TS + 10, tolerance_seconds=300
        )
        is True
    )


def test_verify_rejects_expired_timestamp() -> None:
    header = _header(_PAYLOAD, _SECRET, _TS)
    assert (
        verify_signature(
            payload=_PAYLOAD, secret=_SECRET, header=header, now=_TS + 301, tolerance_seconds=300
        )
        is False
    )


def test_verify_rejects_tampered_body() -> None:
    header = _header(_PAYLOAD, _SECRET, _TS)
    assert (
        verify_signature(
            payload=_PAYLOAD + b"x", secret=_SECRET, header=header, now=_TS, tolerance_seconds=300
        )
        is False
    )


def test_verify_rejects_wrong_secret() -> None:
    header = _header(_PAYLOAD, _SECRET, _TS)
    assert (
        verify_signature(
            payload=_PAYLOAD, secret="d" * 32, header=header, now=_TS, tolerance_seconds=300
        )
        is False
    )


def test_verify_rejects_malformed_header() -> None:
    for bad in ("", "garbage", "t=abc,v1=x", "v1=onlysig"):
        assert (
            verify_signature(
                payload=_PAYLOAD, secret=_SECRET, header=bad, now=_TS, tolerance_seconds=300
            )
            is False
        )
