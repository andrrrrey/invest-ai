"""Email service for sending transactional emails via SMTP."""

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from ..config import settings


def send_registration_email(to_email: str, full_name: str, password: str) -> None:
    """Send registration email with generated password to the new user."""
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        raise RuntimeError(
            "SMTP не настроен. Укажите SMTP_USER и SMTP_PASSWORD в конфигурации сервера."
        )

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
