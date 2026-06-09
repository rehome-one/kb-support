"""HTTP-клиент PaymentReleaseChecker (E10-7, #197) — проверка возможности выплаты.

Поверх resilient-фундамента #70 (AT-003), провизорный контракт (ADR-0014). Config-gated
по пустому `payment_release_checker_api_token` (инертно до ops/#77). Информационна:
результат хранится в payload, case_state НЕ блокирует (ADR-0014 U4 / NFR-4.4).
"""

from api.clients.payment_checker.adapter import HttpPaymentReleaseCheckerClient
from api.clients.payment_checker.models import Clearance
from api.clients.payment_checker.protocol import PaymentReleaseCheckerClient

__all__ = ["Clearance", "HttpPaymentReleaseCheckerClient", "PaymentReleaseCheckerClient"]
