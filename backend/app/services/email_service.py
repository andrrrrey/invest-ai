"""Email service for sending transactional emails via SMTP."""

import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from typing import List, Optional

from ..config import settings

logger = logging.getLogger(__name__)


def send_email_with_attachment(
    to_email: str,
    subject: str,
    text_body: str,
    attachment_bytes: bytes,
    filename: str,
    content_type: str = "text/plain",
) -> None:
    """Отправить письмо с вложением (например, выгрузку логов) через SMTP."""
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        raise RuntimeError(
            "SMTP не настроен. Укажите SMTP_USER и SMTP_PASSWORD в конфигурации сервера."
        )
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))

    maintype, _, subtype = content_type.partition("/")
    part = MIMEApplication(attachment_bytes, _subtype=subtype or "octet-stream")
    part.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(part)

    context = ssl.create_default_context()
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.ehlo()
        server.starttls(context=context)
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, to_email, msg.as_string())


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


def send_registration_email(to_email: str, full_name: str, invite_url: str) -> None:
    """Send a registration invite with a one-time link to set the password.

    The password is never sent by email — the user follows the link and chooses
    their own password.
    """
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
      Установите пароль по ссылке ниже, чтобы войти в систему.
    </p>

    <div style="background: #F2F2F7; border-radius: 12px; padding: 20px; margin-bottom: 24px;">
      <div style="margin-bottom: 4px;">
        <span style="font-size: 13px; color: #8E8E93;">Email:</span>
        <span style="font-size: 13px; font-weight: 600; color: #1C1C1E; margin-left: 8px;">{to_email}</span>
      </div>
    </div>

    <a href="{invite_url}"
       style="display: block; text-align: center; background: #5E5CE6; color: white;
              padding: 14px 28px; border-radius: 12px; font-size: 15px; font-weight: 700;
              text-decoration: none; margin-bottom: 20px;">
      Установить пароль
    </a>

    <p style="font-size: 13px; color: #FF9500; margin: 0 0 24px;">
      ⚠️ Ссылка действительна 24 часа. Если вы не запрашивали регистрацию — проигнорируйте письмо.
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
        f"Установите пароль по ссылке (действительна 24 часа):\n{invite_url}\n\n"
        f"Если вы не запрашивали регистрацию — проигнорируйте это письмо."
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
    "draft": ("Возвращён в черновик", "#FF9500", "#FFF4E5"),
    "rework_needed": ("Отправлен на доработку", "#0055CC", "#E8F2FE"),
}


def send_password_reset_email(to_email: str, full_name: str, reset_url: str) -> None:
    """Send password reset link to the user."""
    subject = "Восстановление пароля | Инвестиционный процессор"

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
      Восстановление пароля
    </h1>
    <p style="font-size: 14px; color: #8E8E93; margin: 0 0 24px;">
      Здравствуйте, {full_name}! Вы запросили сброс пароля.
    </p>

    <a href="{reset_url}"
       style="display: block; text-align: center; background: #5E5CE6; color: white;
              padding: 14px 28px; border-radius: 12px; font-size: 15px; font-weight: 700;
              text-decoration: none; margin-bottom: 20px;">
      Установить новый пароль
    </a>

    <p style="font-size: 13px; color: #FF9500; margin: 0 0 16px;">
      ⚠️ Ссылка действительна 1 час. Если вы не запрашивали сброс — проигнорируйте письмо.
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
        f"Вы запросили сброс пароля в Инвестиционном процессоре.\n\n"
        f"Перейдите по ссылке для установки нового пароля:\n{reset_url}\n\n"
        f"Ссылка действительна 1 час. Если вы не запрашивали сброс — проигнорируйте письмо."
    )

    _send_email(to_email, subject, html_body, text_body)


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
