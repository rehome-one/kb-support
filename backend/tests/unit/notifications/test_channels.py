"""Unit-тесты seam-каналов push/SMS (E7-9, #150) — без сети.

Config-gated: выключен (пустой токен) → не планируется + intent-log без ПДн; включён →
планируется. dispatch never-raise, ПДн не логируется. Реальная доставка — #161.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest import mock

from fastapi import BackgroundTasks

from api.config import Settings
from api.notifications import channels as channels_module
from api.notifications.channels import (
    PushSmsNotice,
    dispatch_push,
    dispatch_sms,
    maybe_schedule_push,
    maybe_schedule_sms,
)
from api.tickets.models import Ticket


def _ticket() -> Ticket:
    return Ticket(id=uuid.uuid4(), number="RH-2026-00042", subject="Оплата")


def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {"sms_api_token": "", "push_api_token": ""}
    base.update(over)
    return Settings(**base)


def test_push_off_not_scheduled() -> None:
    bg = BackgroundTasks()
    assert maybe_schedule_push(bg, _ticket(), "Новый ответ", _settings()) is False
    assert bg.tasks == []


def test_sms_off_not_scheduled() -> None:
    bg = BackgroundTasks()
    assert maybe_schedule_sms(bg, _ticket(), "Новый ответ", _settings()) is False
    assert bg.tasks == []


def test_push_on_scheduled() -> None:
    bg = BackgroundTasks()
    assert maybe_schedule_push(bg, _ticket(), "Новый ответ", _settings(push_api_token="t")) is True
    assert len(bg.tasks) == 1


def test_sms_on_scheduled() -> None:
    bg = BackgroundTasks()
    assert maybe_schedule_sms(bg, _ticket(), "Новый ответ", _settings(sms_api_token="t")) is True
    assert len(bg.tasks) == 1


def _logged(call_list: Any) -> str:
    return " ".join(str(arg) for call in call_list for arg in call.args)


def test_off_intent_logged_without_pii() -> None:
    # Лог намерения при выключенном канале — на DEBUG, БЕЗ ПДн (только номер заявки).
    t = _ticket()
    with mock.patch.object(channels_module._logger, "debug") as dbg:
        maybe_schedule_push(BackgroundTasks(), t, "Новый ответ", _settings())
        maybe_schedule_sms(BackgroundTasks(), t, "Новый ответ", _settings())
    assert dbg.call_count == 2
    logged = _logged(dbg.call_args_list)
    assert "skipped: channel off" in logged
    assert "Новый ответ" not in logged  # сводка/тело в лог не уходит
    # Номер заявки передаётся параметром (ссылка, не ПДн) — не как часть summary.
    assert all("Новый ответ" not in str(a) for call in dbg.call_args_list for a in call.args)


def test_dispatch_never_raises_no_pii() -> None:
    notice = PushSmsNotice(ticket_id=uuid.uuid4(), ticket_number="RH-2026-00042", summary="Решена")
    with mock.patch.object(channels_module._logger, "info") as info:
        dispatch_push(notice, _settings(push_api_token="t"))  # не должно бросить
        dispatch_sms(notice, _settings(sms_api_token="t"))
    logged = _logged(info.call_args_list)
    assert "Решена" not in logged  # сводка не логируется (только ticket_number параметром)
