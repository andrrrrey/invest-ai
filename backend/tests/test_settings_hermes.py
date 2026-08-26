"""Тесты расширенных настроек Hermes/Mattermost (маскирование секретов, персист)."""

from app import settings_store
from app.api.v1.settings import get_settings, update_settings, SettingsUpdate


def test_update_and_get_mattermost_settings():
    update_settings(
        SettingsUpdate(
            mattermost_base_url="https://mm.example.com",
            mattermost_integration_url="https://invest.example.com",
            mattermost_command_token="cmd-secret-1234",
            mattermost_bot_token="bot-secret-5678",
            mattermost_alert_webhook="https://mm.example.com/hooks/abcd",
        ),
        _=None,
    )
    data = get_settings(_=None)

    # URL-поля возвращаются как есть.
    assert data["mattermost_base_url"] == "https://mm.example.com"
    assert data["mattermost_integration_url"] == "https://invest.example.com"

    # Секреты не отдаются в открытом виде — только флаг + маска.
    assert data["mattermost_command_token_set"] is True
    assert data["mattermost_bot_token_set"] is True
    assert data["mattermost_alert_webhook_set"] is True
    assert "cmd-secret-1234" not in str(data)
    assert "bot-secret-5678" not in str(data)
    assert data["mattermost_command_token_masked"].endswith("1234")

    # Но настоящее значение сохранено и читается через store.
    assert settings_store.get_mattermost_bot_token() == "bot-secret-5678"


def test_update_and_get_hermes_flags():
    update_settings(
        SettingsUpdate(
            anonymize_enabled=False,
            anonymize_round_amounts=True,
            reminders_enabled=True,
            hermes_write_enabled=True,
        ),
        _=None,
    )
    data = get_settings(_=None)
    assert data["anonymize_enabled"] is False
    assert data["anonymize_round_amounts"] is True
    assert data["reminders_enabled"] is True
    assert data["hermes_write_enabled"] is True

    # Вернём обезличивание во включённое состояние, чтобы не влиять на другие тесты.
    update_settings(SettingsUpdate(anonymize_enabled=True, hermes_write_enabled=False), _=None)
    assert settings_store.is_anonymize_enabled() is True
    assert settings_store.is_hermes_write_enabled() is False


def test_env_overrides_flag(monkeypatch):
    monkeypatch.setenv("MATTERMOST_BOT_TOKEN", "env-bot-token")
    data = get_settings(_=None)
    assert data["env_overrides"]["mattermost_bot_token"] is True
    # Значение из env имеет приоритет.
    assert settings_store.get_mattermost_bot_token() == "env-bot-token"
