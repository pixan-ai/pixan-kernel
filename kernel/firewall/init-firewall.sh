#!/usr/bin/env bash
# Optional egress firewall (KERNEL_FIREWALL=1, needs --cap-add NET_ADMIN NET_RAW).
# Follows the pattern of Anthropic's reference devcontainer init-firewall.sh:
# default DROP, allow DNS + loopback + established, allow only resolved allowlisted IPs.
# Extra domains: KERNEL_EGRESS_ALLOW="erp.internal example.com" (space separated).
# Extra CIDRs: KERNEL_EGRESS_ALLOW_CIDR="10.0.0.0/8 192.168.1.0/24" (space separated).
set -euo pipefail
IFS=$'\n\t'
# registry.npmjs.org: `bun install` of the Telegram plugin's dependencies.
domains=(api.anthropic.com statsig.anthropic.com sentry.io api.telegram.org registry.npmjs.org)
# The lists are space separated: split them on spaces explicitly (IFS above has no space).
IFS=' ' read -r -a extra <<<"${KERNEL_EGRESS_ALLOW:-}" || true
IFS=' ' read -r -a cidrs <<<"${KERNEL_EGRESS_ALLOW_CIDR:-}" || true
domains+=("${extra[@]}")

iptables -F; iptables -X
ipset destroy allowed-domains 2>/dev/null || true
ipset create allowed-domains hash:net

# GitHub ranges (plugin marketplace + git), as in the reference script.
gh_ranges="$(curl -fsS --max-time 15 https://api.github.com/meta)"
jq -r '(.web + .api + .git)[]' <<<"$gh_ranges" | grep -v ':' | aggregate -q | while read -r cidr; do
  ipset add allowed-domains "$cidr" -exist
done
for d in "${domains[@]}"; do
  [ -n "$d" ] || continue
  ips="$(dig +short A "$d" | grep -E '^[0-9.]+$' || true)"
  [ -n "$ips" ] || { echo "firewall: cannot resolve $d" >&2; exit 1; }
  while read -r ip; do ipset add allowed-domains "$ip" -exist; done <<<"$ips"
done

# Private networks stay reachable only if the operator asks (e.g. an on-prem ERP).
for cidr in "${cidrs[@]}"; do ipset add allowed-domains "$cidr" -exist; done

iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A INPUT  -p udp --sport 53 -j ACCEPT
iptables -A INPUT  -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A INPUT  -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m set --match-set allowed-domains dst -j ACCEPT
iptables -P INPUT DROP; iptables -P FORWARD DROP; iptables -P OUTPUT DROP
iptables -A OUTPUT -j REJECT --reject-with icmp-admin-prohibited
# IPv6: the allowlist is IPv4 only, so everything but loopback is dropped.
if ip6tables -L -n >/dev/null 2>&1; then
  ip6tables -F; ip6tables -X
  ip6tables -A INPUT -i lo -j ACCEPT; ip6tables -A OUTPUT -o lo -j ACCEPT
  ip6tables -P INPUT DROP; ip6tables -P FORWARD DROP; ip6tables -P OUTPUT DROP
else
  echo "firewall: ip6tables unavailable (no IPv6 in this kernel); nothing to drop" >&2
fi

# Self-test, like the reference: a blocked host must fail, Anthropic must pass.
if curl -fsS --max-time 5 https://example.com >/dev/null 2>&1; then
  echo "firewall: example.com reachable, firewall NOT effective" >&2; exit 1
fi
curl -fsS --max-time 10 -o /dev/null https://api.anthropic.com 2>/dev/null || [ "$?" = 22 ] \
  || { echo "firewall: api.anthropic.com unreachable" >&2; exit 1; }
echo "firewall: active (${#domains[@]} domains + GitHub)"
