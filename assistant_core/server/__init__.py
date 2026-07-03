"""HTTP server package.

Re-exports the public surface so existing imports keep working:
    from assistant_core.server import AssistantServer, _fastapi_available
"""

from assistant_core.server.core import AssistantServer
from assistant_core.server.models import _fastapi_available

__all__ = ["AssistantServer", "_fastapi_available"]
