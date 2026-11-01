# Plugin: vercel (publish a static site)

Deploys files to `<sub>.<VERCEL_DOMAIN>` via the Vercel API and only reports success on HTTP 200.

| | |
|---|---|
| Enable | `PIXAN_PLUGINS=vercel` |
| Env | `VERCEL_TOKEN`, `VERCEL_DOMAIN` (required), `VERCEL_TEAM_ID` (several teams only) |
| Needs in client image | nothing |
| Domains | `api.vercel.com`, plus each published host `<sub>.<VERCEL_DOMAIN>` for the 200 check |

Ported from pixan-railway-agent `vercel_publish.py` / `publish-web`. Change: `VERCEL_DOMAIN` has no default.
With `KERNEL_FIREWALL=1` the 200 check needs the published host in `KERNEL_EGRESS_ALLOW` (Vercel IPs).
