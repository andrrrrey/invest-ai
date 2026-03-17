from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Any
from ...services import ai_service
from ... import settings_store

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


def _check_api_key():
    if not settings_store.get_openai_key():
        raise HTTPException(
            status_code=503,
            detail="OpenAI API ключ не настроен. Перейдите в Настройки и введите ключ.",
        )


@router.post("/generate-description")
def generate_description(req: DescriptionRequest) -> dict:
    """Generate project description using OpenAI GPT-4o."""
    _check_api_key()
    text = ai_service.generate_description(
        project_name=req.project_name,
        business_unit=req.business_unit,
        project_type=req.project_type,
        stage=req.stage,
    )
    return {"description": text}


@router.post("/generate-risks")
def generate_risks(req: RisksRequest) -> dict:
    """Generate risks and assumptions using OpenAI GPT-4o."""
    _check_api_key()
    result = ai_service.generate_risks(
        project_name=req.project_name,
        metrics=req.metrics,
        financial_model=req.financial_model,
    )
    return result


@router.post("/generate-risk-score")
def generate_risk_score(req: RiskScoreRequest) -> dict:
    """Generate AI Risk Score for a type 1.2 operational investment request."""
    _check_api_key()
    return ai_service.generate_risk_score(application=req.application)


@router.post("/analyze")
def analyze_project(req: AnalyzeRequest) -> dict:
    """Analyze project anomalies and generate AI commentary."""
    _check_api_key()
    return ai_service.analyze_project(
        project=req.project,
        metrics=req.metrics,
    )
