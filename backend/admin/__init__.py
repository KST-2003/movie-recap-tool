"""Admin dashboard backend: `routes` = the /api/admin/* router (include it in the app), `settings` = values the admin can
change at runtime (maintenance mode, global daily ceiling), `main.py` reads them per request."""
from . import settings  # noqa: F401
from .routes import router  # noqa: F401
