from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Any
from ...services import ai_service
from ... import settings_store
from ...auth import get_current_user

router = APIRouter(prefix="/ai", tags=["ai"])


class DescriptionRequest(BaseModel):
    project_name: str
    business_unit: str
    project_type: str = "investment"
    stage: Optional[str] = None


class RisksRequest(BaseModel):
    project_name: str
    metrics: dict
    financial_model: dict


class RiskScoreRequest(BaseModel):
    application: dict


class AnalyzeRequest(BaseModel):
    project: dict
    metrics: dict


class ExtractAmountRequest(BaseModel):
    text: str
    budget_rows: list = []
    budget_num_years: int = 1


def _check_api_key():
    if not settings_store.is_ai_enabled():
        raise HTTPException(
            status_code=403,
            detail="AI-функции отключены. Включите их в Настройках (передача данных "
                   "во внешние AI-провайдеры разрешается ответственным лицом).",
        )
    provider = settings_store.get_ai_provider()
    key = settings_store.get_anthropic_key() if provider == "anthropic" else settings_store.get_openai_key()
    if not key:
        provider_label = "Anthropic" if provider == "anthropic" else "OpenAI"
        raise HTTPException(
            status_code=503,
            detail=f"{provider_label} API ключ не настроен. Перейдите в Настройки и введите ключ.",
        )


@router.post("/generate-description")
def generate_description(req: DescriptionRequest, _=Depends(get_current_user)) -> dict:
    _check_api_key()
    text = ai_service.generate_description(
        project_name=req.project_name,
        business_unit=req.business_unit,
        project_type=req.project_type,
        stage=req.stage,
    )
    return {"description": text}


@router.post("/generate-risks")
def generate_risks(req: RisksRequest, _=Depends(get_current_user)) -> dict:
    _check_api_key()
    return ai_service.generate_risks(
        project_name=req.project_name,
        metrics=req.metrics,
        financial_model=req.financial_model,
    )


@router.post("/generate-risk-score")
def generate_risk_score(req: RiskScoreRequest, _=Depends(get_current_user)) -> dict:
    _check_api_key()
    return ai_service.generate_risk_score(application=req.application)


@router.post("/analyze")
def analyze_project(req: AnalyzeRequest, _=Depends(get_current_user)) -> dict:
    _check_api_key()
    try:
        return ai_service.analyze_project(
            project=req.project,
            metrics=req.metrics,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка AI-сервиса: {e}")


@router.post("/extract-amount")
def extract_amount(req: ExtractAmountRequest, _=Depends(get_current_user)) -> dict:
    _check_api_key()
    try:
        budget_summary = _build_budget_summary(req.budget_rows, req.budget_num_years)
        amount = ai_service.extract_requested_amount(req.text, budget_summary=budget_summary)
        return {"amount": amount}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка AI-сервиса: {e}")


def _build_budget_summary(budget_rows: list, num_years: int) -> str:
    """Build a human-readable budget summary from structured op_budget_rows."""
    if not budget_rows:
        return ""
    lines = []
    grand_total = 0
    for row in budget_rows:
        cat = row.get("category") or "—"
        monthly_values = row.get("monthlyValues") or []
        row_total = 0
        for year_vals in monthly_values:
            if isinstance(year_vals, list):
                row_total += sum(v for v in year_vals if isinstance(v, (int, float)))
        if row_total:
            lines.append(f"  {cat}: {row_total:,.0f} ₽ (за весь период)")
            grand_total += row_total
    if not lines:
        return ""
    # Also compute monthly average
    total_months = max(num_years * 12, 1)
    monthly_avg = grand_total / total_months
    summary = "Бюджет по статьям (из структурированной таблицы):\n"
    summary += "\n".join(lines)
    summary += f"\nИТОГО за период: {grand_total:,.0f} ₽"
    summary += f"\nСреднемесячно: {monthly_avg:,.0f} ₽/мес"
    return summary
