"""
Разрешённые операции ИИ над данными (только чтение на Этапе 2).

Каждая функция принимает сессию БД и возвращает JSON-сериализуемый результат.
Операции на запись появятся на Этапе 4 под отдельным сервис-аккаунтом.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Optional

from sqlalchemy.orm import Session

from ..models.project import Project
from ..models.fact_entry import FactEntry
from ..models.tranche import Tranche
from ..models.comment import Comment
from ..models.attachment import Attachment
from ..models.audit_log import AuditLog
from ..models.user import User
from ..services import portfolio_service, write_service, links, mattermost_service


def _project_brief(p: Project) -> dict:
    metrics = p.metrics or {}
    return {
        "id": p.id,
        "name": p.name,
        "project_type": p.project_type or "investment",
        "status": p.status or "draft",
        "business_unit": p.business_unit,
        "owner": p.owner,
        "npv": metrics.get("npv"),
        "irr": metrics.get("irr"),
        "url": links.project_url(p.project_type, p.id),
    }


def list_projects(
    db: Session,
    status: Optional[str] = None,
    project_type: Optional[str] = None,
) -> dict:
    """Список проектов с краткими показателями (с опциональной фильтрацией)."""
    q = db.query(Project)
    if status:
        q = q.filter(Project.status == status)
    if project_type:
        q = q.filter(Project.project_type == project_type)
    rows = q.order_by(Project.id.desc()).all()
    return {"count": len(rows), "projects": [_project_brief(p) for p in rows]}


def find_projects(db: Session, query: str) -> dict:
    """Найти проекты по части названия (регистронезависимо).

    Возвращает краткие карточки со ссылками — чтобы обращаться к проекту по
    названию, не зная числового id.
    """
    q = (query or "").strip()
    if not q:
        return {"count": 0, "projects": [], "note": "Пустой запрос поиска"}
    # Регистронезависимый поиск делаем в Python: встроенный lower() в SQLite не
    # понижает регистр кириллицы, поэтому SQL LIKE был бы ненадёжен. Ищем по
    # названию, владельцу, бизнес-юниту и кодам МВЗ.
    needle = q.lower()

    def _matches(p: Project) -> bool:
        haystacks = [p.name, p.owner, p.business_unit]
        fm = p.financial_model or {}
        if isinstance(fm, dict):
            haystacks += [fm.get("op_mvz_main"), fm.get("op_mvz_sub1"), fm.get("op_mvz_sub2")]
        return any(h and needle in str(h).lower() for h in haystacks)

    rows = [p for p in db.query(Project).order_by(Project.id.desc()).all() if _matches(p)]
    return {"count": len(rows), "query": q, "projects": [_project_brief(p) for p in rows]}


_TAG_RE = re.compile(r"<[^>]+>")


def _plain(value) -> Optional[str]:
    """Очистить rich-text (HTML из редактора) до простого текста для ИИ."""
    if value is None:
        return None
    s = _TAG_RE.sub(" ", str(value))
    s = (
        s.replace("&nbsp;", " ").replace("&amp;", "&")
        .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    )
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _operational_content(fm: dict) -> dict:
    """Содержательные поля операционной заявки (текст без HTML)."""
    def _drivers() -> Optional[str]:
        ds = fm.get("op_value_drivers") or []
        other = fm.get("op_value_drivers_other") or ""
        out = [other if d == "__other__" else d for d in ds]
        return "; ".join(str(d) for d in out if d) or None

    mvz = " / ".join(
        str(fm.get(k)) for k in ("op_mvz_main", "op_mvz_sub1", "op_mvz_sub2") if fm.get(k)
    ) or None
    return {
        "category": fm.get("op_category"),
        "mvz": mvz,
        "investment_type": fm.get("op_investment_type"),
        "requested_resource": _plain(fm.get("op_requested_resource")),
        "investment_thesis": _plain(fm.get("op_investment_thesis")),
        "key_metric": _plain(fm.get("op_metrics")),
        "baseline": _plain(fm.get("op_baseline")),
        "target": _plain(fm.get("op_target")),
        "economics": _plain(fm.get("op_economics")),
        "stop_loss": _plain(fm.get("op_stop_loss")),
        "stage_gates": _plain(fm.get("op_stage_gates")),
        "value_drivers": _drivers(),
    }


def get_project(db: Session, project_id: int) -> dict:
    """Детали одного проекта: статус, метрики, уровень риска, история статусов.

    Для операционных заявок содержание (запрашиваемый ресурс, инвестиционный
    тезис, метрика, экономика и т.д.) лежит в financial_model.op_*, а не в
    поле description — поэтому оно добавляется отдельным блоком ``content``.
    """
    p = db.get(Project, project_id)
    if not p:
        return {"error": f"Проект {project_id} не найден"}
    metrics = p.metrics or {}
    risks = p.risks_data or {}
    scd = p.smart_contract_data or {}
    fm = p.financial_model or {}
    ptype = p.project_type or "investment"

    result = {
        "id": p.id,
        "name": p.name,
        "project_type": ptype,
        "status": p.status or "draft",
        "business_unit": p.business_unit,
        "owner": p.owner,
        "stage": p.stage,
        "description": _plain(p.description),
        "metrics": {
            k: metrics.get(k) for k in ("npv", "irr", "dpp", "ltvCac", "pi")
        }
        if metrics
        else {},
        "risk_level": (risks.get("ai_assessment") or {}).get("risk_level")
        or risks.get("overall_risk"),
        "milestones_count": len(scd.get("milestones") or []),
        "status_history": p.status_history or [],
        "url": links.project_url(ptype, p.id),
    }

    # Содержательные поля заявки (для ответа «о чём проект»).
    if ptype == "operational":
        result["content"] = _operational_content(fm)
        vs = p.value_score_data or {}
        result["value_score"] = {"total": vs.get("total"), "band": vs.get("band")}
        result["decision_route"] = p.decision_route
    elif ptype == "smart_contract":
        result["content"] = {
            "short_description": _plain(scd.get("shortDescription")),
            "business_effect": _plain(scd.get("businessEffect")),
            "curator": scd.get("curator"),
        }
    return result


def get_portfolio_stats(db: Session, project_type: Optional[str] = None) -> dict:
    """Агрегированные показатели портфеля (счётчики, NPV, IRR, бюджет и т.д.)."""
    return portfolio_service.compute_stats(db, project_type=project_type, user=None)


def list_pending_approvals(db: Session) -> dict:
    """Проекты, ожидающие согласования (статус pending_approval)."""
    rows = (
        db.query(Project)
        .filter(Project.status == "pending_approval")
        .order_by(Project.id.desc())
        .all()
    )
    return {"count": len(rows), "pending": [_project_brief(p) for p in rows]}


def get_project_facts(db: Session, project_id: int) -> dict:
    """Фактические показатели проекта (план/факт/отклонение)."""
    p = db.get(Project, project_id)
    if not p:
        return {"error": f"Проект {project_id} не найден"}
    rows = db.query(FactEntry).filter(FactEntry.project_id == project_id).all()
    facts = []
    for e in rows:
        pv, fv = e.plan_value, e.fact_value
        dev = (
            round((fv - pv) / pv * 100, 1)
            if (pv not in (None, 0) and fv is not None)
            else None
        )
        facts.append(
            {
                "metric": e.metric_name,
                "year": e.year,
                "month": e.month,
                "plan": pv,
                "fact": fv,
                "deviation_pct": dev,
            }
        )
    return {"project_id": project_id, "count": len(facts), "facts": facts}


def get_milestones(db: Session, project_id: int) -> dict:
    """Майлстоуны смарт-контракта: статус, дедлайн, вознаграждение."""
    p = db.get(Project, project_id)
    if not p:
        return {"error": f"Проект {project_id} не найден"}
    scd = p.smart_contract_data or {}
    milestones = [
        {
            "title": m.get("title") or m.get("name"),
            "status": m.get("status"),
            "deadline": m.get("deadline"),
            "rewardRub": m.get("rewardRub"),
            "coins": m.get("coins"),
        }
        for m in (scd.get("milestones") or [])
        if isinstance(m, dict)
    ]
    return {"project_id": project_id, "count": len(milestones), "milestones": milestones}


_DONE_MILESTONE_STATUSES = {"paid", "done", "completed"}


def _parse_deadline(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return _dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def list_upcoming_deadlines(db: Session, window_days: int = 30) -> dict:
    """Сроки по проектам: незавершённые майлстоуны с приближающимися или
    просроченными дедлайнами (для аналитики по срокам действующих проектов).

    Возвращает список, отсортированный по дедлайну, с флагом просрочки и
    числом дней до дедлайна.
    """
    try:
        window_days = int(window_days)
    except (TypeError, ValueError):
        window_days = 30
    today = _dt.date.today()
    horizon = today + _dt.timedelta(days=window_days)

    projects = (
        db.query(Project)
        .filter(Project.project_type == "smart_contract")
        .all()
    )
    items = []
    for p in projects:
        scd = p.smart_contract_data or {}
        for m in scd.get("milestones") or []:
            if not isinstance(m, dict):
                continue
            if (m.get("status") or "").lower() in _DONE_MILESTONE_STATUSES:
                continue
            deadline = _parse_deadline(m.get("deadline"))
            if not deadline:
                continue
            # Просроченные и попадающие в окно — всё, что <= горизонта.
            if deadline <= horizon:
                items.append({
                    "project_id": p.id,
                    "project": p.name,
                    "milestone": m.get("title") or m.get("name"),
                    "status": m.get("status"),
                    "deadline": deadline.isoformat(),
                    "days_left": (deadline - today).days,
                    "overdue": deadline < today,
                })
    items.sort(key=lambda x: x["deadline"])
    return {
        "window_days": window_days,
        "count": len(items),
        "overdue_count": sum(1 for i in items if i["overdue"]),
        "deadlines": items,
    }


def get_tranches(db: Session, project_id: int) -> dict:
    """Транши проекта: суммы, плановые даты, статусы (requested/approved/paid)."""
    p = db.get(Project, project_id)
    if not p:
        return {"error": f"Проект {project_id} не найден"}
    rows = (
        db.query(Tranche)
        .filter(Tranche.project_id == project_id)
        .order_by(Tranche.order_index, Tranche.id)
        .all()
    )
    tranches = [
        {
            "amount": t.amount,
            "planned_date": t.planned_date,
            "status": t.status,
            "description": t.description,
        }
        for t in rows
    ]
    total = sum((t.amount or 0) for t in rows)
    approved = sum((t.amount or 0) for t in rows if t.status == "approved")
    paid = sum((t.amount or 0) for t in rows if t.status == "paid")
    return {
        "project_id": project_id,
        "count": len(tranches),
        "total_amount": round(total, 2),
        "approved_amount": round(approved, 2),
        "paid_amount": round(paid, 2),
        "tranches": tranches,
    }


def get_comments(db: Session, project_id: int, limit: int = 10) -> dict:
    """Последние комментарии по проекту (кто и когда)."""
    p = db.get(Project, project_id)
    if not p:
        return {"error": f"Проект {project_id} не найден"}
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 10
    rows = (
        db.query(Comment)
        .filter(Comment.project_id == project_id)
        .order_by(Comment.created_at.desc())
        .limit(limit)
        .all()
    )
    comments = [
        {
            "author": (c.author.full_name if c.author else None),
            "text": c.text,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in rows
    ]
    return {"project_id": project_id, "count": len(comments), "comments": comments}


def list_attachments(db: Session, project_id: int) -> dict:
    """Вложения проекта: имя, размер и ссылка на скачивание."""
    p = db.get(Project, project_id)
    if not p:
        return {"error": f"Проект {project_id} не найден"}
    base = links.app_base_url()
    rows = (
        db.query(Attachment)
        .filter(Attachment.project_id == project_id)
        .order_by(Attachment.uploaded_at.desc())
        .all()
    )
    files = [
        {
            "name": a.original_name,
            "size": a.file_size,
            "uploaded_at": a.uploaded_at.isoformat() if a.uploaded_at else None,
            "url": (f"{base}/api/v1/attachments/{a.id}/download" if base else None),
        }
        for a in rows
    ]
    return {"project_id": project_id, "count": len(files), "attachments": files}


def get_forecast(db: Session, project_id: int) -> dict:
    """Ре-прогноз по проекту: сохранённый forecast_data + простой тренд факта.

    Тренд — средняя месячная дельта по каждой метрике с >=2 точками факта.
    """
    p = db.get(Project, project_id)
    if not p:
        return {"error": f"Проект {project_id} не найден"}

    rows = (
        db.query(FactEntry)
        .filter(FactEntry.project_id == project_id, FactEntry.fact_value.isnot(None))
        .order_by(FactEntry.metric_name, FactEntry.year, FactEntry.month)
        .all()
    )
    from collections import defaultdict
    by_metric = defaultdict(list)
    for r in rows:
        by_metric[r.metric_name].append(r)

    trends = []
    for metric, entries in by_metric.items():
        if len(entries) < 2:
            continue
        deltas = [entries[i + 1].fact_value - entries[i].fact_value for i in range(len(entries) - 1)]
        avg_delta = sum(deltas) / len(deltas)
        last = entries[-1]
        trends.append({
            "metric": metric,
            "last_fact": last.fact_value,
            "avg_monthly_delta": round(avg_delta, 4),
            "direction": "рост" if avg_delta > 0 else ("снижение" if avg_delta < 0 else "стабильно"),
        })

    return {
        "project_id": project_id,
        "reforecast": p.forecast_data or [],
        "trends": trends,
    }


def compare_projects(db: Session, project_ids: list) -> dict:
    """Сравнить несколько проектов по ключевым показателям."""
    ids = []
    for pid in (project_ids or []):
        try:
            ids.append(int(pid))
        except (TypeError, ValueError):
            continue
    if not ids:
        return {"error": "Не передан список project_ids"}
    rows = db.query(Project).filter(Project.id.in_(ids)).all()
    found = {p.id: p for p in rows}
    out = []
    for pid in ids:
        p = found.get(pid)
        if not p:
            out.append({"id": pid, "error": "не найден"})
            continue
        m = p.metrics or {}
        vs = p.value_score_data or {}
        out.append({
            "id": p.id,
            "name": p.name,
            "project_type": p.project_type or "investment",
            "status": p.status or "draft",
            "npv": m.get("npv"),
            "irr": m.get("irr"),
            "dpp": m.get("dpp"),
            "value_score": vs.get("total"),
            "risk_level": _risk_level(p),
            "url": links.project_url(p.project_type, p.id),
        })
    return {"count": len(out), "projects": out}


def portfolio_by_dimension(db: Session, dimension: str = "business_unit") -> dict:
    """Сводка портфеля в разрезе: business_unit | owner | project_type | status.

    Для каждой группы — число проектов и суммарный NPV (по инвестиционным,
    кроме отклонённых).
    """
    allowed = {"business_unit", "owner", "project_type", "status"}
    if dimension not in allowed:
        dimension = "business_unit"
    groups: dict = {}
    for p in db.query(Project).all():
        key = getattr(p, dimension, None) or "—"
        g = groups.setdefault(str(key), {"key": str(key), "count": 0, "total_npv": 0.0})
        g["count"] += 1
        m = p.metrics or {}
        if (p.project_type or "investment") == "investment" and (p.status or "") != "rejected":
            try:
                g["total_npv"] += float(m.get("npv") or 0)
            except (TypeError, ValueError):
                pass
    result = sorted(groups.values(), key=lambda x: x["count"], reverse=True)
    for g in result:
        g["total_npv"] = round(g["total_npv"], 2)
    return {"dimension": dimension, "groups": result}


def budget_status(db: Session) -> dict:
    """Статус инвестиционного бюджета: лимит, одобрено (транши), доступно."""
    stats = portfolio_service.compute_stats(db, user=None)
    return {
        "investment_budget": stats.get("investment_budget"),
        "approved_investment": stats.get("approved_investment"),
        "available_for_investment": stats.get("available_for_investment"),
        "total_projects": stats.get("total"),
        "by_status": stats.get("by_status"),
    }


def list_overdue_fact(db: Session, window_months: int = 2) -> dict:
    """Проекты, по которым давно (или ни разу) не обновляли факт.

    Флагуются активные (не rejected/draft) проекты, где последний месяц факта
    старше, чем ``window_months`` от текущего месяца, либо факта нет вовсе.
    """
    try:
        window_months = max(1, int(window_months))
    except (TypeError, ValueError):
        window_months = 2
    today = _dt.date.today()
    threshold_ordinal = today.year * 12 + today.month - window_months

    projects = (
        db.query(Project)
        .filter(Project.project_type != "smart_contract")
        .all()
    )
    overdue = []
    for p in projects:
        if (p.status or "draft") in ("rejected", "draft"):
            continue
        rows = db.query(FactEntry).filter(FactEntry.project_id == p.id).all()
        if not rows:
            overdue.append({"id": p.id, "name": p.name, "last_fact": None,
                            "url": links.project_url(p.project_type, p.id)})
            continue
        last_ord = max(r.year * 12 + r.month for r in rows)
        if last_ord < threshold_ordinal:
            y, m = divmod(last_ord - 1, 12)
            overdue.append({
                "id": p.id, "name": p.name,
                "last_fact": f"{y:04d}-{m + 1:02d}",
                "url": links.project_url(p.project_type, p.id),
            })
    return {"window_months": window_months, "count": len(overdue), "projects": overdue}


def get_audit_trail(db: Session, project_id: int, limit: int = 15) -> dict:
    """История действий по проекту из журнала аудита (кто/что/результат)."""
    p = db.get(Project, project_id)
    if not p:
        return {"error": f"Проект {project_id} не найден"}
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 15
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.target_type == "project", AuditLog.target_id == str(project_id))
        .order_by(AuditLog.id.desc())
        .limit(limit)
        .all()
    )
    events = [
        {
            "action": r.action,
            "actor_type": r.actor_type,
            "result": r.result,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "meta": r.meta,
        }
        for r in rows
    ]
    return {"project_id": project_id, "count": len(events), "events": events}


def risk_overview(db: Session) -> dict:
    """Проекты с высоким уровнем риска (для контроля портфеля)."""
    high = []
    for p in db.query(Project).all():
        level = (_risk_level(p) or "").lower()
        if "высок" in level:
            high.append({
                "id": p.id,
                "name": p.name,
                "project_type": p.project_type or "investment",
                "status": p.status or "draft",
                "risk_level": _risk_level(p),
                "url": links.project_url(p.project_type, p.id),
            })
    return {"count": len(high), "projects": high}


def _risk_level(p: Project):
    risks = p.risks_data or {}
    return (risks.get("ai_assessment") or {}).get("risk_level") or risks.get("overall_risk")


# ── Операции на запись (Этап 4, включаются флагом hermes_write_enabled) ────────

def add_comment(db: Session, project_id: int, text: str) -> dict:
    """Оставить комментарий в проекте (от служебного аккаунта Hermes)."""
    from ..config import settings

    p = db.get(Project, project_id)
    if not p:
        return {"error": f"Проект {project_id} не найден"}
    body = (text or "").strip()
    if not body:
        return {"error": "Пустой текст комментария"}
    bot = db.query(User).filter(User.email == settings.HERMES_BOT_EMAIL).first()
    if not bot:
        return {"error": "Служебный аккаунт Hermes не найден"}
    c = Comment(project_id=project_id, user_id=bot.id, text=f"[via Hermes] {body}")
    db.add(c)
    db.commit()
    return {"ok": True, "project_id": project_id}


def request_fact_update(db: Session, project_id: int) -> dict:
    """Напомнить заявителю обновить факт и статус майлстоунов (DM в Mattermost)."""
    p = db.get(Project, project_id)
    if not p:
        return {"error": f"Проект {project_id} не найден"}
    owner = db.get(User, p.user_id) if p.user_id else None
    email = mattermost_service.mattermost_email(owner)
    if not email:
        return {"error": "У проекта нет ответственного с email для Mattermost"}
    link = links.project_url(p.project_type, p.id)
    msg = f"Просьба обновить фактические показатели по проекту «{p.name or '(без названия)'}»."
    if link:
        msg += f"\n{link}"
    ok = mattermost_service.post_to_email(email, msg)
    return {"ok": bool(ok), "project_id": project_id}


def update_fact(db: Session, project_id: int, entries: list) -> dict:
    """Обновить фактические/плановые значения по метрикам проекта."""
    return write_service.update_fact(db, project_id, entries, actor_type="hermes")


def update_milestone_status(db: Session, project_id: int, index: int, status: str) -> dict:
    """Изменить статус майлстоуна смарт-контракта."""
    return write_service.update_milestone_status(
        db, project_id, index, status, actor_type="hermes"
    )
