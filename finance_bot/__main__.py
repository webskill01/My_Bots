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


def setup_logging() -> None:
    """Routine logs to stdout, trouble to stderr.

    logging's default is stderr for everything, which makes pm2 file every
    INFO line in the error log and paint it red. Splitting the streams means
    red in `pm2 logs` genuinely means something went wrong.
    """
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    out = logging.StreamHandler(sys.stdout)
    out.setFormatter(fmt)
    out.addFilter(lambda record: record.levelno < logging.WARNING)

    err = logging.StreamHandler(sys.stderr)
    err.setFormatter(fmt)
    err.setLevel(logging.WARNING)

    logging.basicConfig(level=logging.INFO, handlers=[out, err])
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    setup_logging()

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
