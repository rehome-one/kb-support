"""HTTP-клиент доставки решения в ЛК заявителя (E10-7 PR-2, #197).

Поверх resilient-фундамента #70 (AT-003), провизорный контракт (ADR-0014/0006). Цель —
платформа rehome.one (переиспользует `platform_api_*`, тот же сосед, что #71; gate по
пустому `platform_api_token`, инертно до #77). Связь только по HTTP (арх-константа).
"""

from api.clients.lk_notify.adapter import HttpLkNotifyClient
from api.clients.lk_notify.models import DecisionNotification
from api.clients.lk_notify.protocol import LkNotifyClient

__all__ = ["DecisionNotification", "HttpLkNotifyClient", "LkNotifyClient"]
