"""HTTP-клиент BankProvider (E10-7, #197) — запрос выплаты по решению претензии.

Поверх resilient-фундамента #70 (AT-003), провизорный контракт (ADR-0014, стиль
ADR-0006/0010 Реш.4). Config-gated по пустому `bank_provider_api_token` (инертно до
ops/#77). Связь только по HTTP (арх-константа): kb-support деньги НЕ считает (FR-9.8),
лишь запрашивает выплату и хранит ссылку (`linked_payment_id`).
"""

from api.clients.bank.adapter import HttpBankProviderClient
from api.clients.bank.models import PayoutRequest, PayoutResult
from api.clients.bank.protocol import BankProviderClient

__all__ = ["BankProviderClient", "HttpBankProviderClient", "PayoutRequest", "PayoutResult"]
