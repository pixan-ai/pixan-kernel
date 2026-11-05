# Security policy

Report vulnerabilities privately via GitHub Security Advisories on this repository
(Security tab, "Report a vulnerability"; private vulnerability reporting is enabled).
Never open a public issue with secrets or exploit details.

## Scope

pixan-kernel is Claude Code set up well for a 24/7 agent. It is not a security product, and it is
provided AS IS (Apache 2.0). Known limits, by design:

- The optional firewall resolves allowed host names **once, at boot**. New provider IPs need a restart.
- `Read`/`Edit` deny rules cover Claude's file tools, not every subprocess it runs.
- The SSRF guard checks DNS twice before `WebFetch`, but the fetch resolves again on its own and may follow
  redirects; it narrows DNS rebinding, it does not eliminate it.
- The secret filter (backups, owner alerts) matches known token shapes and the container's own secret
  variables. It is best effort.

## Repository hardening

- `main` is protected by a ruleset: changes land through pull requests, and the required checks
  `L0 static + unit`, `L1 entrypoint` and `L2 image build + smoke (publishes the tested image on main)`
  must pass. Deleting `main` and force-pushing to it are blocked. An admin bypass exists as a guardrail
  against accidents, not as a hard lock.
- Only pushes to `main` publish the image, and they publish the exact image L2 tested.
