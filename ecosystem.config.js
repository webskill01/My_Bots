// PM2 runs the venv's python directly: "python finance_bot/__main__.py" would
// break the package-relative imports, so it has to be "python -m finance_bot".
module.exports = {
  apps: [{
    name: "finance-bot",
    cwd: "/opt/my-bots",
    script: "/opt/my-bots/.venv/bin/python",
    args: "-m finance_bot",
    interpreter: "none",

    // Telegram allows exactly one long-poll per token. A second instance
    // makes both sides fail with HTTP 409, so never cluster this.
    instances: 1,
    exec_mode: "fork",

    autorestart: true,
    restart_delay: 5000,
    max_memory_restart: "300M",
    env: { PYTHONUNBUFFERED: "1" },  // otherwise pm2 logs lag behind
  }],
};
