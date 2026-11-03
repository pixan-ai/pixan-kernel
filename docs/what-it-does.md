# What the kernel does (and what it doesn't)

The kernel is **Claude Code set up well to work as a 24/7 agent**, talking to you through the official Telegram plugin. It is built from official pieces: Claude Code, Anthropic's Telegram plugin, and plain-text instructions (`.md`).

## What it adds

- **Scheduled tasks that don't expire** (`cron.py`): they run on time, survive restarts, and deliver the result to you on Telegram. Claude Code's native tasks expire after 7 days and can start up to 30 min late, so they are turned off here.
- **The exact time** (`clock.py`): Claude Code only gives the agent the date.
- **Heartbeat**: checks every 30 s that the agent is still alive; if not, the container restarts.
- **Rich messages**: tables, images, and HTML in Telegram. If they can't be turned on, Telegram keeps working normally.
- **Basic safety rules**: official Claude Code rules (managed settings) and a check that stops the agent from opening internal network addresses. They are an extra safety net, not a guarantee.
- **Outbound internet allowlist (optional, off)**: if you turn it on (`KERNEL_FIREWALL=1`), the agent can only connect to the sites on the list. It is **off** by default.

## What it does NOT promise

- **It is not a security product.** Nothing here guarantees that the agent won't make mistakes, be tricked, or cause harm.
- **It does not guarantee availability**, or that it works without errors with every new version of Claude Code or Telegram.
- **It does not replace your backups** or your review of what the agent does in your systems.

## How the agent acts

The agent runs with `--dangerously-skip-permissions`: **it acts without asking you** at each step. This is **your decision** as the client, so it can work on its own 24 hours a day. That is why we recommend giving it read-only access to your systems until you decide otherwise, and using keys with limited permissions.

## License

The software is provided **"AS IS"**, without warranties of any kind, under the **Apache 2.0** license (see [`LICENSE`](../LICENSE)).
