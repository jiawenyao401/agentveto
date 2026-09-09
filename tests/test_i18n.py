"""Tests for i18n: localized VetoError reasons."""

from __future__ import annotations

import os

import pytest

from agentveto import i18n
from agentveto.veto import Decision, VetoError, evaluate, guard


# ------------------ i18n helpers ------------------------------------------


def test_localize_plain_string():
    assert i18n.localize("hello") == "hello"


def test_localize_dict_exact_match(monkeypatch):
    reason = {"en": "outbound blocked", "zh": "外发被拦截"}
    monkeypatch.setenv("AGENTVETO_LANG", "zh")
    assert i18n.localize(reason) == "外发被拦截"
    monkeypatch.setenv("AGENTVETO_LANG", "en")
    assert i18n.localize(reason) == "outbound blocked"


def test_localize_dict_falls_back_to_en(monkeypatch):
    reason = {"en": "blocked", "zh": "拦截"}
    monkeypatch.setenv("AGENTVETO_LANG", "ja")  # not present
    assert i18n.localize(reason) == "blocked"


def test_localize_dict_falls_back_to_any_string():
    reason = {"de": "blockiert"}  # no en, no match for default lang
    assert i18n.localize(reason) == "blockiert"


def test_localize_non_string_non_dict():
    assert i18n.localize(42) == "42"


def test_current_lang_priority(monkeypatch):
    monkeypatch.delenv("AGENTVETO_LANG", raising=False)
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    assert i18n.current_lang() == "zh"

    monkeypatch.setenv("AGENTVETO_LANG", "fr")
    assert i18n.current_lang() == "fr"

    monkeypatch.delenv("AGENTVETO_LANG", raising=False)
    monkeypatch.delenv("LANG", raising=False)
    assert i18n.current_lang() == "en"


# ------------------ Decision + VetoError ---------------------------------


def test_decision_reason_text_localizes(monkeypatch):
    d = Decision("deny", action="send_email", rule="r", reason={"en": "blocked", "zh": "拦截"})
    monkeypatch.setenv("AGENTVETO_LANG", "zh")
    assert d.reason_text() == "拦截"
    monkeypatch.setenv("AGENTVETO_LANG", "en")
    assert d.reason_text() == "blocked"


def test_decision_str_localizes(monkeypatch):
    d = Decision("deny", action="send_email", rule="no-mail", reason={"en": "no mail", "zh": "禁止发邮件"})
    monkeypatch.setenv("AGENTVETO_LANG", "zh")
    assert "禁止发邮件" in str(d)


def test_veto_error_message_localizes(monkeypatch):
    monkeypatch.setenv("AGENTVETO_LANG", "zh")
    d = Decision("deny", action="send_email", rule="r", reason={"zh": "外发禁止"})
    err = VetoError(d)
    assert "外发禁止" in str(err)


def test_evaluate_returns_dict_reason():
    P = {
        "rules": [
            {
                "name": "no-mail",
                "action": "send_email",
                "effect": "deny",
                "reason": {"en": "blocked", "zh": "拦截"},
            }
        ]
    }
    d = evaluate(P, "send_email", {})
    assert d.effect == "deny"
    assert isinstance(d.reason, dict)


def test_guard_error_message_in_active_language(monkeypatch):
    monkeypatch.setenv("AGENTVETO_LANG", "zh")
    P = {
        "rules": [
            {
                "name": "no-mail",
                "action": "send_email",
                "effect": "deny",
                "reason": {"en": "blocked", "zh": "禁止外发"},
            }
        ]
    }

    @guard(P, action="send_email")
    def send_email(to):
        return "sent"

    with pytest.raises(VetoError) as exc:
        send_email("bob@x.com")
    assert "禁止外发" in str(exc.value)
