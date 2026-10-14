"""
Построение ссылок на страницы приложения (для бота, карточек и ответов агента).

Базовый URL берётся из настроек (``app_base_url`` / env ``APP_BASE_URL``), с
фолбэком на внешний URL бэкенда (``mattermost_integration_url``) — в типовом
развёртывании фронтенд и API живут на одном домене (nginx).
"""

from __future__ import annotations

from typing import Optional

from .. import settings_store

# Тип проекта -> путь страницы карточки.
_PATH_BY_TYPE = {
    "operational": "/op-project",
    "smart_contract": "/smart-contract",
}

# Тип проекта -> человекочитаемое название (для сообщений бота).
_LABEL_BY_TYPE = {
    "investment": "Инвестиционный проект",
    "operational": "Операционная заявка",
    "smart_contract": "Смарт-контракт",
}


def project_type_label(project_type: Optional[str]) -> str:
    """Русское название типа проекта для уведомлений (по умолчанию — инвестиционный)."""
    return _LABEL_BY_TYPE.get(project_type or "", _LABEL_BY_TYPE["investment"])


def label_for(project) -> str:
    """Название типа конкретного проекта; для контрактов различает смарт-
    и лидерский контракт (``smart_contract_data.scType``)."""
    if (getattr(project, "project_type", None) or "") == "smart_contract":
        from .contract_utils import contract_label
        return contract_label(project)
    return project_type_label(getattr(project, "project_type", None))


def project_path(project_type: Optional[str], project_id) -> str:
    """Относительный путь карточки проекта (для ссылок в уведомлениях)."""
    path = _PATH_BY_TYPE.get(project_type or "", "/project")
    return f"{path}?id={project_id}"


def app_base_url() -> Optional[str]:
    base = settings_store.get_app_base_url()
    return base.rstrip("/") if base else None


def project_url(project_type: Optional[str], project_id) -> Optional[str]:
    """Абсолютная ссылка на карточку проекта или ``None``, если база не задана."""
    base = app_base_url()
    if not base or project_id is None:
        return None
    path = _PATH_BY_TYPE.get(project_type or "", "/project")
    return f"{base}{path}?id={project_id}"
