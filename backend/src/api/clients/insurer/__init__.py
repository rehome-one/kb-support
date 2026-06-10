"""HTTP-клиент страховщика — outbound передача события (E10-10 PR-B #200; ADR-0014:67/0017 D3).

Поверх resilient-фундамента #70 (AT-003), провизорный контракт. Config-gated по пустому
`insurer_api_token` (инертно до ops/#77). **Мутация (передача события) → raise** при сбое
(как BankProvider, ADR-0010 Реш.4); ловится фоновым таском never-raise (`insurer_dispatch`).
ПДн наружу не передаём (только `{ticket_id, insurance_event_id}`, ФЗ-152).
"""

from api.clients.insurer.adapter import HttpInsurerClient
from api.clients.insurer.models import InsurerEvent
from api.clients.insurer.protocol import InsurerClient

__all__ = ["HttpInsurerClient", "InsurerClient", "InsurerEvent"]
