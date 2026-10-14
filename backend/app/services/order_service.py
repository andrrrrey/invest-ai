"""Проект приказа (ЛНА) на основании согласованного контракта / проекта.

1. Генерация текста: AI по скиллу «Постановка задач через ЛНА, план работ и
   приказ» (``prompts/lna_plan_prikaz.md``). Если AI выключен или не ответил —
   приказ собирается по шаблону из того же скилла (данные подставляются из
   контракта), чтобы кнопка работала всегда.
2. Сборка .docx в фирменном формате ПравоТеха (Times New Roman, шапка, дата/№,
   «ПРИКАЗЫВАЮ», нумерованные пункты, подпись, приложение — план работ).
3. Файл сохраняется во вложения карточки, затем Баффет запускает маршрут
   согласования C&B → юрист → CEO (``route_service``, route='order').
"""

from __future__ import annotations

import datetime as dt
import io
import json
import logging
import os
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import settings_store
from ..models.attachment import Attachment
from ..models.project import Project
from ..models.user import User
from . import audit_service, links, route_service
from .contract_notifications import notify_user
from .contract_utils import sc_type_of

logger = logging.getLogger("hermes.orders")

ATTACHMENTS_DIR = os.environ.get("ATTACHMENTS_DIR", "/data/attachments")
_SKILL_PATH = Path(__file__).resolve().parent.parent / "prompts" / "lna_plan_prikaz.md"

COMPANY_HEADER = ["НЕПУБЛИЧНОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО", "«ПРАВОТЕХ»"]
DEFAULT_SIGNER = ("Генеральный директор", "А.М. Пелевин")

PLAN_COLUMNS = ["№", "Результат", "Срок", "Критерий качества", "Ресурсы и полномочия", "Подтверждение"]


# ── Данные ───────────────────────────────────────────────────────────────

def _d(value) -> str:
    if not value:
        return "«__» _______ 20__ г."
    v = str(value)[:10]
    try:
        return dt.date.fromisoformat(v).strftime("%d.%m.%Y")
    except ValueError:
        return v


def _person(project: Project) -> str:
    return project.owner or "работника"


def contract_facts(project: Project) -> dict:
    scd = project.smart_contract_data or {}
    kind = sc_type_of(project)
    start = scd.get("startDate") or (project.created_at.date().isoformat() if project.created_at else None)
    return {
        "kind": "лидерский контракт" if kind == "leadership" else "смарт-контракт",
        "is_leadership": kind == "leadership",
        "name": project.name or "",
        "business_unit": project.business_unit or "",
        "owner": _person(project),
        "curator": scd.get("curator") or "",
        "customer": scd.get("customerName") or "",
        "start": start,
        "deadline": scd.get("deadline"),
        "short": scd.get("shortDescription") or project.description or "",
        "effect": scd.get("businessEffect") or "",
        "fixed": scd.get("fixedSalaryMonthly"),
        "variable": scd.get("variableTotal"),
        "milestones": scd.get("milestones") or [],
        "team": scd.get("team") or [],
    }


def _plan_rows_from_milestones(f: dict) -> List[dict]:
    acceptor = f["curator"] or f["customer"] or "куратором контракта"
    rows = []
    for m in f["milestones"]:
        result = m.get("name") or "Этап"
        if m.get("target"):
            result += f": {m.get('target')}"
        rows.append({
            "result": result,
            "deadline": _d(m.get("deadline")),
            "criterion": m.get("criteria") or "—",
            "resources": "В пределах должностных полномочий; ресурсы предоставляются по согласованию "
                         f"с {acceptor}",
            "confirmation": f"Отчёт с данными из источника: {m.get('dataSource')}" if m.get("dataSource")
                            else "Отчёт о выполнении по форме, согласованной с куратором",
        })
    return rows


def template_contract_order(project: Project) -> dict:
    """Приказ по шаблону скилла (без AI)."""
    f = contract_facts(project)
    acceptor = f["curator"] or f["customer"] or "куратора контракта"
    period = f"с {_d(f['start'])} по {_d(f['deadline'])}"
    articles = "ст. 15, 21, 22, 274 Трудового кодекса РФ" if f["is_leadership"] else "ст. 15, 21, 22 Трудового кодекса РФ"
    return {
        "title": f"Об утверждении плана работ и постановке задач {f['owner']}",
        "preamble": (
            f"В целях конкретизации трудовой функции {f['owner']}, порядка доведения до него задач "
            f"и обеспечения системного контроля за выполнением возложенных на него задач в рамках "
            f"{'лидерского контракта' if f['is_leadership'] else 'смарт-контракта'} «{f['name']}», "
            f"на основании {articles},"
        ),
        "points": [
            f"Утвердить план работ {f['owner']} на период {period} согласно приложению к настоящему приказу.",
            f"Установить, что отчёты о выполнении плана представляются {acceptor} в срок до 5-го числа "
            "месяца, следующего за отчётным периодом.",
            f"Определить {acceptor} лицом, принимающим результаты выполнения задач, указанных в плане работ.",
            f"Установить, что факт невыполнения или ненадлежащего выполнения задачи фиксируется актом / "
            f"служебной запиской {acceptor} в срок не позднее 5 рабочих дней после истечения установленного срока.",
            f"Ознакомить {f['owner']} с настоящим приказом и планом работ под подпись в срок до "
            "«__» _______ 20__ г. При отказе от ознакомления составить акт.",
            "Контроль за исполнением настоящего приказа оставляю за собой.",
        ],
        "appendix_title": f"План работ {f['owner']} на период {period}",
        "appendix_columns": PLAN_COLUMNS,
        "appendix_rows": [
            [str(i), r["result"], r["deadline"], r["criterion"], r["resources"], r["confirmation"]]
            for i, r in enumerate(_plan_rows_from_milestones(f), start=1)
        ],
        "signer_position": DEFAULT_SIGNER[0],
        "signer_name": DEFAULT_SIGNER[1],
        "review_notes": [
            "Проверьте соответствие задач должности и квалификации работника, реальность сроков и "
            "зависимость результата от самого работника (ст. 15, 192 ТК РФ).",
        ],
    }


def _skill_text() -> str:
    try:
        return _SKILL_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def ai_contract_order(project: Project) -> dict:
    """Текст приказа от AI по скиллу. Возвращает структуру как у шаблона."""
    from . import ai_service

    f = contract_facts(project)
    ms_lines = "\n".join(
        f"  {i}. {m.get('name') or '—'} — срок {_d(m.get('deadline'))}; критерий: {m.get('criteria') or '—'}; "
        f"было: {m.get('baseline') or '—'}; цель: {m.get('target') or '—'}; источник: {m.get('dataSource') or '—'}"
        for i, m in enumerate(f["milestones"], start=1)
    ) or "  (этапы не заданы)"
    money = (
        f"Оклад {f['fixed'] or 0} ₽/мес; переменная часть {f['variable'] or 0} ₽ за период."
        if f["is_leadership"] else f"Команда: {', '.join(t.get('name') or '' for t in f['team']) or '—'}."
    )
    prompt = (
        "Ниже — методика (скилл) подготовки документов о постановке задач. Следуй ей.\n"
        "=== СКИЛЛ ===\n" + _skill_text() + "\n=== КОНЕЦ СКИЛЛА ===\n\n"
        "Задача: подготовить ПРОЕКТ ПРИКАЗА об утверждении плана работ и постановке задач и приложение — "
        f"план работ, на основании согласованного {f['kind']}а. Используй фирменный формат ПравоТеха. "
        "Не задавай вопросов — все вводные ниже; недостающее оставь прочерками («__»).\n\n"
        f"— Контракт: «{f['name']}» ({f['kind']}), бизнес-юнит: {f['business_unit'] or '—'}\n"
        f"— Работник (ответственный): {f['owner']}\n"
        f"— Куратор: {f['curator'] or '—'}; заказчик: {f['customer'] or '—'}\n"
        f"— Период: с {_d(f['start'])} по {_d(f['deadline'])}\n"
        f"— Суть: {f['short'] or '—'}\n— Бизнес-эффект: {f['effect'] or '—'}\n— {money}\n"
        f"— Этапы (станут задачами плана):\n{ms_lines}\n\n"
        "Каждую задачу плана сформулируй по формуле «Результат — Срок — Критерий качества — Ресурсы и "
        "полномочия — Форма подтверждения».\n"
        "Верни ТОЛЬКО JSON без Markdown:\n"
        '{"title": "Об утверждении плана работ и постановке задач ...",'
        ' "preamble": "В целях ..., на основании ст. ... Трудового кодекса РФ,",'
        ' "points": ["текст пункта 1 без номера", "..."],'
        ' "appendix_title": "План работ ... на период с ... по ...",'
        ' "plan_rows": [{"result": "...", "deadline": "ДД.ММ.ГГГГ", "criterion": "...", "resources": "...", "confirmation": "..."}],'
        ' "signer_position": "Генеральный директор", "signer_name": "А.М. Пелевин",'
        ' "review_notes": ["что проверить юристу перед подписанием"]}'
    )
    raw = ai_service._chat(
        prompt, max_tokens=4000,
        extra_terms={"project": [f["name"]], "person": [f["owner"], f["curator"], f["customer"]]},
        action="ai.order", target_type="project", target_id=str(project.id),
    )
    data = json.loads(ai_service._strip_fences(raw))
    points = [str(p).strip() for p in data.get("points") or [] if str(p).strip()]
    rows = data.get("plan_rows") or []
    if not data.get("title") or not points:
        raise ValueError("AI вернул неполный приказ")
    return {
        "title": str(data["title"]).strip(),
        "preamble": str(data.get("preamble") or "").strip(),
        "points": points,
        "appendix_title": str(data.get("appendix_title") or "План работ").strip(),
        "appendix_columns": PLAN_COLUMNS,
        "appendix_rows": [
            [str(i), str(r.get("result") or ""), str(r.get("deadline") or ""), str(r.get("criterion") or ""),
             str(r.get("resources") or ""), str(r.get("confirmation") or "")]
            for i, r in enumerate(rows, start=1)
        ],
        "signer_position": str(data.get("signer_position") or DEFAULT_SIGNER[0]),
        "signer_name": str(data.get("signer_name") or DEFAULT_SIGNER[1]),
        "review_notes": [str(n) for n in data.get("review_notes") or []],
    }


# ── .docx ────────────────────────────────────────────────────────────────

def build_order_docx(order: dict) -> bytes:
    """Собрать .docx приказа по параметрам форматирования из скилла."""
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin, sec.right_margin = Cm(3), Cm(1.5)
    sec.top_margin, sec.bottom_margin = Cm(2), Cm(2)

    def _font(style_or_run, size=12, bold=None):
        f = style_or_run.font
        f.name = "Times New Roman"
        f.size = Pt(size)
        if bold is not None:
            f.bold = bold
        el = style_or_run.element if hasattr(style_or_run, "element") else style_or_run._element
        rpr = el.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = rpr.makeelement(qn("w:rFonts"), {})
            rpr.append(rfonts)
        for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            rfonts.set(qn(attr), "Times New Roman")

    _font(doc.styles["Normal"], 12)
    _font(doc.styles["List Number"], 12)

    def para(text="", *, align=None, size=12, bold=False, space_before=0, space_after=0, indent_first=None):
        p = doc.add_paragraph()
        if text:
            run = p.add_run(text)
            _font(run, size, bold)
        pf = p.paragraph_format
        pf.space_before, pf.space_after = Pt(space_before), Pt(space_after)
        if align is not None:
            p.alignment = align
        if indent_first is not None:
            pf.first_line_indent = indent_first
        return p

    def no_borders(table):
        tbl_pr = table._tbl.tblPr
        borders = tbl_pr.makeelement(qn("w:tblBorders"), {})
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            borders.append(borders.makeelement(qn(f"w:{edge}"), {qn("w:val"): "nil"}))
        tbl_pr.append(borders)

    for line in COMPANY_HEADER:
        para(line, align=WD_ALIGN_PARAGRAPH.CENTER, size=14, bold=True)
    para("", space_after=6)
    para("ПРИКАЗ", align=WD_ALIGN_PARAGRAPH.CENTER, size=14, space_after=12)

    t = doc.add_table(rows=1, cols=2)
    no_borders(t)
    left, right = t.rows[0].cells
    left.paragraphs[0].add_run("«__» _______ 20__ г.")
    rp = right.paragraphs[0]
    rp.add_run("№ ___")
    rp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for c in (left, right):
        for r in c.paragraphs[0].runs:
            _font(r, 12)
    para("Москва", align=WD_ALIGN_PARAGRAPH.CENTER, space_before=6, space_after=12)

    para(order["title"], align=WD_ALIGN_PARAGRAPH.CENTER, size=12, bold=True, space_after=12)
    if order.get("preamble"):
        para(order["preamble"], align=WD_ALIGN_PARAGRAPH.JUSTIFY, indent_first=Cm(1.25), space_after=6)
    para("ПРИКАЗЫВАЮ", space_before=6, space_after=6)
    for point in order["points"]:
        p = doc.add_paragraph(style="List Number")
        _font(p.add_run(point), 12)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.space_before, p.paragraph_format.space_after = Pt(6), Pt(4)

    if order.get("appendix_rows"):
        para(f"Приложение: {(order.get('appendix_title') or 'план работ').rstrip('.')}.", space_before=12)

    sig = doc.add_table(rows=1, cols=2)
    no_borders(sig)
    sl, sr = sig.rows[0].cells
    _font(sl.paragraphs[0].add_run(order.get("signer_position") or DEFAULT_SIGNER[0]), 12)
    _font(sr.paragraphs[0].add_run(order.get("signer_name") or DEFAULT_SIGNER[1]), 12)
    sr.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for c in (sl, sr):
        pf = c.paragraphs[0].paragraph_format
        pf.space_before, pf.space_after = Pt(14), Pt(14)

    if order.get("appendix_rows"):
        new_sec = doc.add_section()
        new_sec.orientation = WD_ORIENT.LANDSCAPE
        new_sec.page_width, new_sec.page_height = Cm(29.7), Cm(21)
        new_sec.left_margin = new_sec.right_margin = Cm(2)
        # Гриф приложения: отдельный абзац с отступом 4536 twips (≈ 8 см)
        for line in ("Приложение", "к приказу", "от «__» _______ 20__ г. № ___"):
            g = para(line)
            g.paragraph_format.left_indent = Pt(4536 / 20)
        para("", space_after=6)
        para(order.get("appendix_title") or "План работ", align=WD_ALIGN_PARAGRAPH.CENTER, size=14, bold=True, space_after=10)
        cols = order.get("appendix_columns") or PLAN_COLUMNS
        table = doc.add_table(rows=1, cols=len(cols))
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        for cell, title in zip(table.rows[0].cells, cols):
            cell.paragraphs[0].text = ""
            _font(cell.paragraphs[0].add_run(title), 11, True)
        for row in order["appendix_rows"]:
            cells = table.add_row().cells
            for cell, value in zip(cells, row):
                _font(cell.paragraphs[0].add_run(str(value)), 11)
        # Ширины колонок плана: узкий «№» и «Срок», остальное — поровну.
        if len(cols) == len(PLAN_COLUMNS):
            widths = [Cm(1.0), Cm(5.5), Cm(2.6), Cm(5.5), Cm(5.0), Cm(5.1)]
            table.autofit = False
            for row in table.rows:
                for cell, w in zip(row.cells, widths):
                    cell.width = w

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ── Сохранение и маршрут ─────────────────────────────────────────────────

def _save_attachment(db: Session, project: Project, user: User, content: bytes, filename: str) -> Attachment:
    project_dir = os.path.join(ATTACHMENTS_DIR, str(project.id))
    os.makedirs(project_dir, exist_ok=True)
    stored = f"{uuid.uuid4().hex}.docx"
    with open(os.path.join(project_dir, stored), "wb") as fh:
        fh.write(content)
    att = Attachment(project_id=project.id, uploaded_by_id=user.id, filename=stored,
                     original_name=filename, file_size=len(content))
    db.add(att)
    db.flush()
    return att


def _order_filename(project: Project) -> str:
    safe = "".join(ch for ch in (project.name or "") if ch.isalnum() or ch in " -_").strip()[:60]
    return f"Проект приказа — {safe or project.id} ({dt.date.today():%d.%m.%Y}).docx"


def can_generate(db: Session, project: Project, user: User) -> bool:
    if user.role in ("cfo", "manager"):
        return True
    if project.user_id == user.id or project.created_by_id == user.id:
        return True
    from . import approval_roles
    return "cb" in approval_roles.roles_of(db, user)


def _ensure_ready(db: Session, project: Project, user: User) -> None:
    if (project.status or "") != "approved":
        raise HTTPException(status_code=400, detail="Проект приказа формируется по согласованному документу")
    if not can_generate(db, project, user):
        raise HTTPException(status_code=403, detail="Сформировать приказ могут ответственный, C&B, CFO и менеджер")
    active = route_service.active_step(db, project.id, "order")
    if active is not None:
        raise HTTPException(status_code=409, detail="Проект приказа уже на согласовании — дождитесь решения или возврата на доработку")


def build_order(db: Session, project: Project) -> tuple[dict, str]:
    """Текст приказа: AI при включённых AI-функциях, иначе — шаблон."""
    if (project.project_type or "") == "smart_contract":
        template, ai_builder = template_contract_order, ai_contract_order
    else:
        from . import project_orders
        template, ai_builder = project_orders.template_project_order, project_orders.ai_project_order
    if settings_store.is_ai_enabled():
        try:
            return ai_builder(project), "ai"
        except Exception:
            logger.exception("AI order generation failed for project %s — fallback to template", project.id)
    return template(project), "template"


def generate(db: Session, project: Project, user: User) -> dict:
    _ensure_ready(db, project, user)
    route_service.validate_route(db, project, "order")
    order, source = build_order(db, project)
    content = build_order_docx(order)
    att = _save_attachment(db, project, user, content, _order_filename(project))
    project.order_data = {
        "attachment_id": att.id,
        "generated_by_id": user.id,
        "generated_by": user.full_name,
        "generated_at": dt.datetime.utcnow().isoformat(),
        "source": source,
        "title": order["title"],
        "review_notes": order.get("review_notes") or [],
    }
    db.commit()
    audit_service.log_event(
        action="order.generated", actor_type="user", actor_id=str(user.id),
        target_type="project", target_id=str(project.id), meta={"source": source}, db=db,
    )
    route_service.start_route(db, project, "order", user, attachment_id=att.id)
    return project.order_data


def upload_revision(db: Session, project: Project, user: User, content: bytes, filename: str) -> dict:
    """Загрузить исправленный проект приказа (после доработки) и отправить заново."""
    _ensure_ready(db, project, user)
    if not filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Загрузите файл .docx")
    if not content or len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Пустой файл или больше 25 МБ")
    route_service.validate_route(db, project, "order")
    att = _save_attachment(db, project, user, content, filename)
    data = dict(project.order_data or {})
    data.update({"attachment_id": att.id, "generated_by_id": user.id, "generated_by": user.full_name,
                 "generated_at": dt.datetime.utcnow().isoformat(), "source": "upload"})
    project.order_data = data
    db.commit()
    route_service.start_route(db, project, "order", user, attachment_id=att.id)
    return project.order_data


def order_state(db: Session, project: Project, viewer: User) -> dict:
    data = dict(project.order_data or {})
    att = db.get(Attachment, data["attachment_id"]) if data.get("attachment_id") else None
    return {
        "order": data or None,
        "attachment": {"id": att.id, "name": att.original_name, "size": att.file_size} if att else None,
        "route": route_service.route_state(db, project, "order", viewer),
        "can_generate": (project.status or "") == "approved" and can_generate(db, project, viewer),
    }


def _initiator(db: Session, project: Project) -> Optional[User]:
    uid = (project.order_data or {}).get("generated_by_id")
    return db.get(User, uid) if uid else None


def _on_order_complete(db: Session, project: Project, actor: User, comment) -> None:
    data = dict(project.order_data or {})
    data["approved_at"] = dt.datetime.utcnow().isoformat()
    project.order_data = data
    db.commit()
    for u in {x.id: x for x in filter(None, [_initiator(db, project), db.get(User, project.user_id) if project.user_id else None])}.values():
        notify_user(db, u, project=project, title="Проект приказа согласован",
                    message=f"Проект приказа по «{project.name}» согласован C&B, юристом и CEO — можно передавать на подписание.",
                    anchor="order")


def _on_order_rework(db: Session, project: Project, actor: User, comment) -> None:
    initiator = _initiator(db, project)
    notify_user(db, initiator, project=project, title="Проект приказа возвращён на доработку",
                message=f"{actor.full_name}: {comment or 'без комментария'}. Загрузите исправленный файл в карточке.",
                anchor="order")


route_service.register_hooks("order", on_complete=_on_order_complete, on_rework=_on_order_rework)
