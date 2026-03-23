# Register all models so SQLAlchemy sees them before init_db()
from .user import User  # noqa: F401
from .project import Project  # noqa: F401
