# Plugin: mail (IMAP/SMTP)

`info`, `ls`, `get`, `send`. `send` refuses without `--i-confirm-send` (the agent must confirm with the owner first).

| | |
|---|---|
| Enable | `PIXAN_PLUGINS=mail` |
| Env | `MAIL_ADDRESS`, `MAIL_APP_PASSWORD` (required), `MAIL_IMAP_HOST`, `MAIL_SMTP_HOST` (default Gmail), `MAIL_TO_ALLOWLIST` (CSV) |
| Needs in client image | nothing (stdlib) |
| Domains / ports | the IMAP host (993) and SMTP host (465), default `imap.gmail.com`, `smtp.gmail.com` |

Ported from pixan-railway-agent `mail.py` / `mail` skill, same behavior and exit codes.
