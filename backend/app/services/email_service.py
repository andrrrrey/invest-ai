"""Email service for sending transactional emails via SMTP."""

import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List

from ..config import settings

logger = logging.getLogger(__name__)


def _send_email(to_email: str, subject: str, html_body: str, text_body: str) -> None:
    """Low-level helper to send an email via SMTP."""
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        raise RuntimeError(
            "SMTP не настроен. Укажите SMTP_USER и SMTP_PASSWORD в конфигурации сервера."
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.ehlo()
        server.starttls(context=context)
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, to_email, msg.as_string())


def send_registration_email(to_email: str, full_name: str, password: str) -> None:
    """Send registration email with generated password to the new user."""
    subject = "Добро пожаловать в Инвестиционный процессор"

    html_body = f"""
<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"></head>
<body style="font-family: 'Segoe UI', Arial, sans-serif; background: #f5f5f5; padding: 40px 0;">
  <div style="max-width: 480px; margin: 0 auto; background: white; border-radius: 16px;
              padding: 40px; box-shadow: 0 4px 20px rgba(0,0,0,0.08);">
    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 32px;">
      <div style="width: 44px; height: 44px; background: #5E5CE6; border-radius: 12px;
                  display: flex; align-items: center; justify-content: center; font-size: 22px;">
        📈
      </div>
      <div>
        <div style="font-size: 16px; font-weight: 700; color: #1C1C1E;">Инвестиционный процессор</div>
        <div style="font-size: 12px; color: #8E8E93;">Платформа управления проектами</div>
      </div>
    </div>

    <h1 style="font-size: 22px; font-weight: 800; color: #1C1C1E; margin: 0 0 8px;">
      Ваш аккаунт создан
    </h1>
    <p style="font-size: 14px; color: #8E8E93; margin: 0 0 28px;">
      Здравствуйте, {full_name}! Вы успешно зарегистрированы как <strong>Заявитель</strong>.
    </p>

    <div style="background: #F2F2F7; border-radius: 12px; padding: 20px; margin-bottom: 24px;">
      <div style="font-size: 12px; font-weight: 700; color: #8E8E93; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px;">
        Ваши данные для входа
      </div>
      <div style="margin-bottom: 10px;">
        <span style="font-size: 13px; color: #8E8E93;">Email:</span>
        <span style="font-size: 13px; font-weight: 600; color: #1C1C1E; margin-left: 8px;">{to_email}</span>
      </div>
      <div>
        <span style="font-size: 13px; color: #8E8E93;">Пароль:</span>
        <span style="font-size: 15px; font-weight: 700; color: #5E5CE6; margin-left: 8px;
                     font-family: 'Courier New', monospace; letter-spacing: 1px;">{password}</span>
      </div>
    </div>

    <p style="font-size: 13px; color: #FF9500; margin: 0 0 24px;">
      ⚠️ Рекомендуем сменить пароль после первого входа.
    </p>

    <p style="font-size: 12px; color: #C7C7CC; margin: 0; text-align: center;">
      Это письмо отправлено автоматически. Не отвечайте на него.
    </p>
  </div>
</body>
</html>
"""

    text_body = (
        f"Здравствуйте, {full_name}!\n\n"
        f"Вы успешно зарегистрированы в Инвестиционном процессоре в роли Заявителя.\n\n"
        f"Email: {to_email}\n"
        f"Пароль: {password}\n\n"
        f"Рекомендуем сменить пароль после первого входа."
    )

    _send_email(to_email, subject, html_body, text_body)


def _email_wrapper(project_name: str) -> tuple:
    """Return (header_html, footer_html) for project notification emails."""
    header = """<div style="display: flex; align-items: center; gap: 12px; margin-bottom: 32px;">
      <div style="width: 44px; height: 44px; background: #5E5CE6; border-radius: 12px;
                  display: flex; align-items: center; justify-content: center; font-size: 22px;">📈</div>
      <div>
        <div style="font-size: 16px; font-weight: 700; color: #1C1C1E;">Инвестиционный процессор</div>
        <div style="font-size: 12px; color: #8E8E93;">Платформа управления проектами</div>
      </div>
    </div>"""
    footer = """<p style="font-size: 12px; color: #C7C7CC; margin: 24px 0 0; text-align: center;">
      Это письмо отправлено автоматически. Не отвечайте на него.</p>"""
    return header, footer


_STATUS_LABELS = {
    "approved": ("Утверждён", "#34C759", "#DDF0E1"),
    "rejected": ("Отклонён", "#FF3B30", "#FFE5E5"),
    "draft": ("Возвращён на доработку", "#FF9500", "#FFF4E5"),
}


def send_approval_request_emails(
    recipients: List[dict], project_name: str, applicant_name: str
) -> None:
    """Notify CFO/managers that a new project awaits approval.

    recipients: list of {"email": str, "full_name": str}
    """
    header, footer = _email_wrapper(project_name)

    for r in recipients:
        subject = f"Новая заявка на согласование: {project_name}"
        html_body = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"></head>
<body style="font-family: 'Segoe UI', Arial, sans-serif; background: #f5f5f5; padding: 40px 0;">
  <div style="max-width: 480px; margin: 0 auto; background: white; border-radius: 16px;
              padding: 40px; box-shadow: 0 4px 20px rgba(0,0,0,0.08);">
    {header}
    <h1 style="font-size: 20px; font-weight: 800; color: #1C1C1E; margin: 0 0 8px;">
      Новая заявка на согласование
    </h1>
    <p style="font-size: 14px; color: #8E8E93; margin: 0 0 20px;">
      Здравствуйте, {r["full_name"]}!
    </p>
    <div style="background: #F2F2F7; border-radius: 12px; padding: 20px; margin-bottom: 20px;">
      <p style="margin: 0 0 8px; font-size: 13px; color: #8E8E93;">ПРОЕКТ</p>
      <p style="margin: 0 0 12px; font-size: 15px; font-weight: 700; color: #1C1C1E;">{project_name}</p>
      <p style="margin: 0; font-size: 13px; color: #8E8E93;">Заявитель: <strong style="color: #1C1C1E;">{applicant_name}</strong></p>
    </div>
    <p style="font-size: 14px; color: #43434d;">
      Пожалуйста, рассмотрите заявку и примите решение в системе.
    </p>
    {footer}
  </div>
</body></html>"""

        text_body = (
            f"Здравствуйте, {r['full_name']}!\n\n"
            f"Новая заявка на согласование: {project_name}\n"
            f"Заявитель: {applicant_name}\n\n"
            f"Пожалуйста, рассмотрите заявку и примите решение в системе."
        )

        try:
            _send_email(r["email"], subject, html_body, text_body)
        except Exception:
            logger.exception("Failed to send approval request email to %s", r["email"])


def send_status_notification_email(
    to_email: str, full_name: str, project_name: str, new_status: str
) -> None:
    """Notify the project applicant about a status change (approved/rejected/draft)."""
    label, color, bg_color = _STATUS_LABELS.get(
        new_status, (new_status, "#8E8E93", "#F2F2F7")
    )
    header, footer = _email_wrapper(project_name)

    subject = f"Статус заявки обновлён: {project_name}"
    html_body = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"></head>
<body style="font-family: 'Segoe UI', Arial, sans-serif; background: #f5f5f5; padding: 40px 0;">
  <div style="max-width: 480px; margin: 0 auto; background: white; border-radius: 16px;
              padding: 40px; box-shadow: 0 4px 20px rgba(0,0,0,0.08);">
    {header}
    <h1 style="font-size: 20px; font-weight: 800; color: #1C1C1E; margin: 0 0 8px;">
      Статус заявки обновлён
    </h1>
    <p style="font-size: 14px; color: #8E8E93; margin: 0 0 20px;">
      Здравствуйте, {full_name}!
    </p>
    <div style="background: #F2F2F7; border-radius: 12px; padding: 20px; margin-bottom: 20px;">
      <p style="margin: 0 0 8px; font-size: 13px; color: #8E8E93;">ПРОЕКТ</p>
      <p style="margin: 0 0 12px; font-size: 15px; font-weight: 700; color: #1C1C1E;">{project_name}</p>
      <p style="margin: 0; font-size: 13px; color: #8E8E93;">НОВЫЙ СТАТУС</p>
      <span style="display: inline-block; margin-top: 6px; padding: 6px 14px; border-radius: 10px;
                   font-size: 13px; font-weight: 700; color: {color}; background: {bg_color};">{label}</span>
    </div>
    {footer}
  </div>
</body></html>"""

    text_body = (
        f"Здравствуйте, {full_name}!\n\n"
        f"Статус вашей заявки «{project_name}» обновлён.\n"
        f"Новый статус: {label}\n\n"
        f"Войдите в систему для подробностей."
    )

    try:
        _send_email(to_email, subject, html_body, text_body)
    except Exception:
        logger.exception("Failed to send status notification email to %s", to_email)
