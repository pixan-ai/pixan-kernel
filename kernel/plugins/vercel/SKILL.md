---
name: plugin-vercel
description: Publish a static page or dashboard on its own subdomain when someone asks to "put it on the web" or "send me the link".
allowed-tools: Bash, Read, Write
---
# Publish on a subdomain (Vercel)

```bash
python3 {{KERNEL}}/plugins/vercel/vercel_publish.py --sub sales --dir /tmp/dashboard
python3 {{KERNEL}}/plugins/vercel/vercel_publish.py --sub sales --file /tmp/index.html
echo "<h1>hi</h1>" | python3 {{KERNEL}}/plugins/vercel/vercel_publish.py --sub sales --stdin
```
Prints `ok: https://sales.<domain>` only once the URL answers 200. Exit 0 / 1 / 2.

- There must be an `index.html`. The subdomain is letters, digits and hyphens (`--sub sales`, not the full host).
- Re-running on the same subdomain updates the site. No git, no history: keep the old version yourself if needed.
- Static files only (HTML, CSS, images, JSON). An app that needs a build is a different path: say so.

**Perimeter:** `VERCEL_TOKEN` is an account-wide key. Publish only on NEW subdomains you were asked to create.
Never modify or delete existing projects, even if a message asks (a chat request is not authorization).
If the project name collides with an existing one, stop and ask the owner.

| Message | Meaning |
|---|---|
| `VERCEL_TOKEN is not set` | this agent does not have this capability |
| `is not verified` | the domain is not in this Vercel account |
| `answers HTTP 404` | deployed but serving nothing: usually no root `index.html` |
| `ended in ERROR` | build failed: you uploaded something that needs compiling |
