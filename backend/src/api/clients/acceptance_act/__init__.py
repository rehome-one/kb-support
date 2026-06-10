"""HTTP-клиент AcceptanceAct (E10-9 PR-A, #199; ADR-0016 D1, ADR-0014).

Резолв состояния акта приёмки-передачи (`signing_status`, `damage_amount`) по сети.
Поверх resilient-фундамента #70 (AT-003), провизорный контракт. Config-gated по пустому
`acceptance_act_api_token` (инертно до ops/#77). **Мягкая деградация → None** (read, как
PaymentReleaseChecker #197): недоступность/не-200/битый JSON → None + WARN.
"""

from api.clients.acceptance_act.adapter import HttpAcceptanceActClient
from api.clients.acceptance_act.models import AcceptanceAct
from api.clients.acceptance_act.protocol import AcceptanceActClient

__all__ = ["AcceptanceAct", "AcceptanceActClient", "HttpAcceptanceActClient"]
