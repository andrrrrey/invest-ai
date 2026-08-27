from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database import get_db
from ...models.user import User
from ...auth import get_current_user
from ...services import portfolio_service

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/")
def get_stats(
    project_type: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Aggregated portfolio stats for the dashboard.
    Owners see stats only for their own projects.
    When project_type is provided, stats are scoped to that type
    (used by the smart-contracts dashboard).
    """
    return portfolio_service.compute_stats(db, project_type=project_type, user=current_user)
