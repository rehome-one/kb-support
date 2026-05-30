"""Unit-тесты маскирования ПДн (NFR-1.5)."""

from __future__ import annotations

import pytest

from api.observability.pii_mask import mask_pii


@pytest.mark.parametrize(
    "raw",
    [
        "пишите на a.b+c@mail.example.ru пожалуйста",
        "телефон +7 (909) 123-45-67",
        "тел 89091234567",
        "паспорт 4509 123456 выдан",
        "СНИЛС 112-233-445 95",
        "ИНН 7707083893",
    ],
)
def test_pii_is_masked(raw: str) -> None:
    masked = mask_pii(raw)
    assert "***" in masked
    # ни одного фрагмента из ≥6 цифр/символов @ не должно остаться
    assert "@mail.example.ru" not in masked
    assert "9091234567" not in masked
    assert "123456" not in masked
    assert "7707083893" not in masked


def test_non_pii_untouched() -> None:
    text = "заявка RH-2026-00042 статус OPEN приоритет high"
    assert mask_pii(text) == text


def test_email_replaced_with_mask() -> None:
    assert mask_pii("john@example.com") == "***"
