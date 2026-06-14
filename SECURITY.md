# Security Policy

## Supported Versions

Security fixes are handled on the `main` branch.

## Reporting A Vulnerability

Please do not open public issues for secrets, token leaks, or exploitable behavior.

Report security concerns privately by email: `irinyakov2016@yandex.ru`.

Useful details:

- affected command, Docker service, or Telegram bot flow;
- expected and actual behavior;
- logs with secrets removed;
- operating system and Python version;
- whether the issue requires a real Telegram token or market-data account.

## Secret Handling

- Never commit a real `.env` file.
- Use `.env.example` as the configuration template.
- Treat `TELEGRAM_BOT_TOKEN` and chat identifiers as deployment secrets.
- Generated MP4 files are runtime artifacts; do not commit user-specific outputs unless they are deliberate demos.

