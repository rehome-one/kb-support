"""HMAC-SHA256 подпись исходящих webhook с anti-replay (E10-8 PR-A #198; ADR-0015 D3).

Чистый модуль (без I/O). Stripe-style: timestamp ВКЛЮЧЁН в подписываемую строку —
иначе голый `X-Webhook-Timestamp`-заголовок не покрыт HMAC и не даёт replay-защиты
(ADR-0015 У2). Потребитель — диспетчер доставки PR-B.

Формат:
- подписываемая строка = `f"{timestamp}."` + raw JSON-body (байты);
- `v1` = HMAC-SHA256(secret, подписываемая строка) в hex;
- заголовок `X-Signature: t={timestamp},v1={v1}` (+ `X-Webhook-Timestamp: {timestamp}`).
"""

from __future__ import annotations

import hashlib
import hmac


def compute_signature(*, payload: bytes, secret: str, timestamp: int) -> str:
    """HMAC-SHA256 (hex) над `f"{timestamp}." + payload` секретом подписки."""
    signed = f"{timestamp}.".encode() + payload
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def signature_header(*, payload: bytes, secret: str, timestamp: int) -> str:
    """Значение заголовка `X-Signature` для доставки события подписчику."""
    digest = compute_signature(payload=payload, secret=secret, timestamp=timestamp)
    return f"t={timestamp},v1={digest}"


def verify_signature(
    *, payload: bytes, secret: str, header: str, now: int, tolerance_seconds: int
) -> bool:
    """Проверить входящую подпись `X-Signature` (`t=<unix>,v1=<hex>`) — для inbound (PR-C).

    True только при валидной HMAC-подписи И `|now - t| <= tolerance_seconds` (anti-replay,
    ADR-0015 D3). Любой парс-сбой / несовпадение / просрочка → False (fail-closed). Сравнение
    подписи — constant-time (`hmac.compare_digest`)."""
    try:
        fields = dict(part.split("=", 1) for part in header.split(","))
        timestamp = int(fields["t"])
        provided = fields["v1"]
    except (ValueError, KeyError):
        return False
    if abs(now - timestamp) > tolerance_seconds:
        return False
    expected = compute_signature(payload=payload, secret=secret, timestamp=timestamp)
    return hmac.compare_digest(expected, provided)
