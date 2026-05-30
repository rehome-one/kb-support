"""Unit-тесты RFC 7807 problem+json ошибок (без БД)."""

from __future__ import annotations

import json

from api.errors import PROBLEM_CONTENT_TYPE, ProblemException, render_problem


def test_unauthorized_factory() -> None:
    exc = ProblemException.unauthorized(detail="nope")
    assert exc.status == 401
    assert exc.title == "Unauthorized"
    assert exc.type.endswith("/unauthorized")
    assert exc.detail == "nope"


def test_not_found_factory_without_detail() -> None:
    exc = ProblemException.not_found()
    assert exc.status == 404
    assert exc.detail is None


def test_render_includes_detail_and_errors() -> None:
    exc = ProblemException(
        status=422,
        title="Validation failed",
        type_="https://api.rehome.one/errors/validation",
        detail="bad input",
        errors=[{"field": "subject", "message": "required"}],
    )
    resp = render_problem(exc)
    assert resp.status_code == 422
    assert resp.media_type == PROBLEM_CONTENT_TYPE
    body = json.loads(bytes(resp.body))
    assert body["status"] == 422
    assert body["detail"] == "bad input"
    assert body["errors"][0]["field"] == "subject"


def test_render_omits_optional_fields_when_absent() -> None:
    body = json.loads(bytes(render_problem(ProblemException.not_found()).body))
    assert "errors" not in body
    assert "detail" not in body
    assert body["title"] == "Not Found"
