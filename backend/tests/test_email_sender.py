"""SMTP_FROM с кириллическим именем не должен ломать отправку писем."""

import email
from email.header import decode_header, make_header

import pytest

from app.services import email_service


class _FakeSMTP:
    sent = []

    def __init__(self, host, port):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        pass

    def sendmail(self, from_addr, to_addr, msg):
        # Реальный smtplib кодирует MAIL FROM в ASCII — проверяем то же самое.
        from_addr.encode("ascii")
        msg.encode("ascii")
        _FakeSMTP.sent.append((from_addr, to_addr, msg))


@pytest.fixture
def smtp(monkeypatch):
    _FakeSMTP.sent = []
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(email_service.settings, "SMTP_USER", "robot@invest.ru")
    monkeypatch.setattr(email_service.settings, "SMTP_PASSWORD", "x")
    return _FakeSMTP.sent


@pytest.mark.parametrize("smtp_from, envelope, name", [
    ("noreply@invest.ru", "noreply@invest.ru", ""),
    ("Инвест-платформа <noreply@invest.ru>", "noreply@invest.ru", "Инвест-платформа"),
    ('"Инвест-платформа" <noreply@invest.ru>', "noreply@invest.ru", "Инвест-платформа"),
    ("Инвест-платформа noreply@invest.ru", "noreply@invest.ru", "Инвест-платформа"),
    ("Инвестплатформа", "robot@invest.ru", "Инвестплатформа"),
    ("noreply@инвест.рф", "noreply@xn--b1aghuwg.xn--p1ai", ""),
])
def test_send_email_with_cyrillic_sender(smtp, monkeypatch, smtp_from, envelope, name):
    monkeypatch.setattr(email_service.settings, "SMTP_FROM", smtp_from)

    email_service._send_email("user@pravo.tech", "Статус проекта", "<p>ok</p>", "ok")

    from_addr, to_addr, raw = smtp[0]
    assert from_addr == envelope
    assert to_addr == "user@pravo.tech"
    header = str(make_header(decode_header(email.message_from_string(raw)["From"])))
    assert envelope in header
    assert name in header


def test_attachment_email_uses_ascii_envelope(smtp, monkeypatch):
    monkeypatch.setattr(email_service.settings, "SMTP_FROM", "Инвест-платформа")
    email_service.send_email_with_attachment("a@b.ru", "Логи", "см. вложение", b"{}", "logs.json", "application/json")
    assert smtp[0][0] == "robot@invest.ru"


def test_no_valid_sender_raises(smtp, monkeypatch):
    monkeypatch.setattr(email_service.settings, "SMTP_FROM", "Инвест-платформа")
    monkeypatch.setattr(email_service.settings, "SMTP_USER", "robot")
    with pytest.raises(RuntimeError, match="SMTP_FROM"):
        email_service._send_email("a@b.ru", "s", "h", "t")
