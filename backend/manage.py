"""Admin commands:
  python manage.py create-user EMAIL PASSWORD [--minutes N] [--admin]
  python manage.py set-minutes EMAIL N        # daily allowance
  python manage.py deactivate EMAIL | activate EMAIL
  python manage.py users                      # list users and today's usage
  python manage.py cleanup                    # delete expired local files now"""
import sys

from sqlalchemy import select

import auth
import storage
from config import DEFAULT_DAILY_MINUTES
from db import Session, User, used_seconds_today


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    cmd, args = argv[0], argv[1:]
    with Session() as s:
        if cmd == "create-user":
            email, password = args[0].lower(), args[1]
            minutes = int(args[args.index("--minutes") + 1]) if "--minutes" in args else DEFAULT_DAILY_MINUTES
            s.add(User(email=email, password_hash=auth.hash_password(password), daily_minutes=minutes, is_admin="--admin" in args))
            s.commit()
            print(f"created {email} ({minutes} min/day)")
        elif cmd in ("set-minutes", "deactivate", "activate"):
            user = s.execute(select(User).where(User.email == args[0].lower())).scalar_one_or_none()
            if not user:
                print("no such user")
                return 1
            if cmd == "set-minutes":
                user.daily_minutes = int(args[1])
            else:
                user.is_active = cmd == "activate"
            s.commit()
            print("ok")
        elif cmd == "users":
            for u in s.execute(select(User).order_by(User.id)).scalars():
                print(f"{u.id:>4} {u.email:<35} {u.daily_minutes:>4} min/day  used today {used_seconds_today(s, u.id) / 60:5.1f} min"
                      f"{'  admin' if u.is_admin else ''}{'' if u.is_active else '  DISABLED'}")
        elif cmd == "cleanup":
            print(f"removed {storage.cleanup()} file(s)")
        else:
            print(__doc__)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
