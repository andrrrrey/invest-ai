from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Any
from ...services import ai_service
from ...config import settings

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


class AnalyzeRequest(BaseModel):
    project: dict
    metrics: dict


def _check_api_key():
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY не настроен. Добавьте его в файл .env",
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


@router.post("/analyze")
def analyze_project(req: AnalyzeRequest) -> dict:
    """Analyze project anomalies and generate AI commentary."""
    _check_api_key()
    return ai_service.analyze_project(
        project=req.project,
        metrics=req.metrics,
    )
