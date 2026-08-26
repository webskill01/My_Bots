"""Entry point: python -m finance_bot"""

import logging
import os
import sys

from . import bot, db


def load_env(path: str = ".env") -> None:
    # ponytail: four lines beats a python-dotenv dependency for KEY=value.
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())
    except FileNotFoundError:
        pass


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    load_env()
    token = os.environ.get("BOT_TOKEN")
    if not token:
        sys.exit("BOT_TOKEN is not set. Copy .env.example to .env and paste the "
                 "token from @BotFather.")

    conn = db.connect(os.environ.get("DB_PATH", "finance.db"))
    db.init(conn)
    logging.info("finance tracker starting")
    bot.build(token, conn).run_polling()


if __name__ == "__main__":
    main()
