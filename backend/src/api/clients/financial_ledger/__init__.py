"""HTTP-клиент FinancialLedger (E10-7 PR-2, #197) — фиксация решения как проводки-ссылки.

Поверх resilient-фундамента #70 (AT-003), провизорный контракт (ADR-0014). Config-gated
по пустому `financial_ledger_api_token` (инертно до ops/#77). kb-support деньги НЕ считает
(FR-9.8) — только фиксирует ссылку. Связь только по HTTP (арх-константа).
"""

from api.clients.financial_ledger.adapter import HttpFinancialLedgerClient
from api.clients.financial_ledger.models import LedgerEntry, LedgerResult
from api.clients.financial_ledger.protocol import FinancialLedgerClient

__all__ = ["FinancialLedgerClient", "HttpFinancialLedgerClient", "LedgerEntry", "LedgerResult"]
