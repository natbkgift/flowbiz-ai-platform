"""PostgreSQL persistence foundation for FlowBiz Platform.

This package is intentionally not wired into FastAPI routes in PROD-04.
Runtime cutover remains a later owner-authorized PR.
"""

from platform_app.db.base import Base

__all__ = ["Base"]
