"""Entry point: python -m schedule_bot  (web panel + push reminders)"""

import os

from finance_bot.__main__ import load_env, setup_logging  # same repo, same .env

from . import panel


def main() -> None:
    setup_logging()
    load_env()
    panel.serve(os.environ.get("SCHEDULE_DB_PATH", "schedule.db"))


if __name__ == "__main__":
    main()
