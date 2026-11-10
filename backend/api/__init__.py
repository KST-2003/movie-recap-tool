"""User-facing API routers: `accounts` (register/login/session), `jobs` (upload/status/edit), `catalog` (public
voice/look samples), `files` (signed downloads). main.py includes each router; the admin API lives in admin/."""
from . import accounts, catalog, files, jobs  # noqa: F401
