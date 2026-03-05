from fastapi import APIRouter
from ...schemas.finance import FinancialModelInput, FinancialMetrics
from ...services.finance_service import calculate_metrics

router = APIRouter(prefix="/finance", tags=["finance"])


@router.post("/calculate", response_model=FinancialMetrics)
def calculate(model: FinancialModelInput) -> FinancialMetrics:
    """
    Server-side financial calculation endpoint.
    Returns the same metrics as the client-side JS engine.
    Used for final validation when saving a project.
    """
    return calculate_metrics(model)
