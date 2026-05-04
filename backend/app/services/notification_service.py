from sqlalchemy.orm import Session

from ..models.notification import Notification
from ..models.user import User


def create_notification(
    db: Session,
    user_id: int,
    title: str,
    message: str,
    project_id: int | None = None,
    link: str | None = None,
) -> Notification:
    n = Notification(
        user_id=user_id,
        project_id=project_id,
        title=title,
        message=message,
        link=link,
    )
    db.add(n)
    return n


def notify_approvers(db: Session, project_id: int, project_name: str, applicant_name: str) -> None:
    approvers = (
        db.query(User)
        .filter(User.role.in_(["cfo", "manager"]), User.is_active == True)
        .all()
    )
    for u in approvers:
        create_notification(
            db,
            user_id=u.id,
            title=f"Новая заявка на согласование",
            message=f"«{project_name}» — подал(а) {applicant_name}",
            project_id=project_id,
            link=f"/project?id={project_id}",
        )


def notify_owner(db: Session, owner_id: int, project_id: int, project_name: str, new_status: str) -> None:
    status_labels = {
        "approved": "Утверждён",
        "rejected": "Отклонён",
        "draft": "Возвращён на доработку",
        "pending_approval": "Отправлен на согласование",
    }
    label = status_labels.get(new_status, new_status)
    create_notification(
        db,
        user_id=owner_id,
        title=f"Статус проекта изменён",
        message=f"«{project_name}» — {label}",
        project_id=project_id,
        link=f"/project?id={project_id}",
    )
