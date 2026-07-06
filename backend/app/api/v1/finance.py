from fastapi import APIRouter, Depends, HTTPException
from ...schemas.finance import FinancialModelInput, FinancialMetrics
from ...services.finance_service import calculate_metrics
from ...auth import get_current_user

router = APIRouter(prefix="/finance", tags=["finance"])

# Guardrails against resource-exhaustion (DoS) via oversized calculation inputs.
_MAX_YEARS = 30
_MAX_PRODUCTS = 50


@router.post("/calculate", response_model=FinancialMetrics)
def calculate(
    model: FinancialModelInput,
    _current_user=Depends(get_current_user),
) -> FinancialMetrics:
    """
    Server-side financial calculation endpoint. Requires authentication.
    Returns the same metrics as the client-side JS engine.
    Used for final validation when saving a project.
    """
    if model.numYears > _MAX_YEARS:
        raise HTTPException(
            status_code=422,
            detail=f"numYears не может превышать {_MAX_YEARS}.",
        )
    if len(model.products) > _MAX_PRODUCTS:
        raise HTTPException(
            status_code=422,
            detail=f"Слишком много продуктов (максимум {_MAX_PRODUCTS}).",
        )
    return calculate_metrics(model)
