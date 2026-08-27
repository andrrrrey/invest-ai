# Register all models so SQLAlchemy sees them before init_db()
# Order matters: User and Project must come before models that FK-reference them
from .user import User  # noqa: F401
from .project import Project  # noqa: F401
from .comment import Comment  # noqa: F401
from .attachment import Attachment  # noqa: F401
from .tranche import Tranche, TriggerChecklistItem, TrancheHistory  # noqa: F401
from .fact_entry import FactEntry  # noqa: F401
from .notification import Notification  # noqa: F401
from .audit_log import AuditLog  # noqa: F401
