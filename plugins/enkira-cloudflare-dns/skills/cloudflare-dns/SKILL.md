---
name: cloudflare-dns
description: Use when creating, reading, updating, or deleting Cloudflare DNS records (CNAME, A, TXT, MX). Use when pointing a subdomain at an Azure Container App, AWS endpoint, or any origin. Use when looking up the zone ID for an Enkira-owned domain.
---

# Cloudflare DNS

CRUD for DNS records via Cloudflare's REST API. Token lives in the `shared-infra` Infisical project — nothing is stored on disk.

## Prerequisites

1. Run `infisical login` once (see `enkira-infisical` skill / `managing-infisical`).
2. `CLOUDFLARE_API_TOKEN` must be set in `shared-infra` → env `prod` → path `/`. Required Cloudflare scope: **Zone:DNS:Edit** on the target zones.

If the token shows `<SET-ME>` in `shared-infra`, ask an admin to fill it before proceeding — the token is created in the Cloudflare dashboard under **My Profile → API Tokens → Create Token → Edit zone DNS**.

## BEFORE USE — verify token scope covers your target zone

**REMIND THE USER:** the current `CLOUDFLARE_API_TOKEN` in `shared-infra` was originally minted for specific panbot zones (`panbot.ai`, `novaserve.ai`). Using it against a different zone will return `9109: Unauthorized to access requested resource`.

Before running DNS mutations, verify the token can see the target zone:

```bash
infisical run --projectId=d231f36b-1287-4d5b-a122-123f239b6131 --env=prod -- \
  bash -c 'curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
    "https://api.cloudflare.com/client/v4/zones?name='"$ZONE_NAME"'" | python3 -m json.tool | head -20'
```

If `result` is empty → the token lacks access to that zone. Options:

1. **Preferred (org-wide):** mint a new token in Cloudflare → My Profile → API Tokens → "Edit zone DNS" → select **all** team zones → overwrite `CLOUDFLARE_API_TOKEN` in `shared-infra` (see `managing-infisical` skill).
2. **Per-project:** store a zone-specific token in the current repo's own Infisical project under `/cloud/` and read from there instead of `shared-infra`.

## Load the token (no file writes)

Every command in this skill should prefix with `infisical run` so the token is injected as an env var and never touches disk:

```bash
infisical run \
  --projectId=d231f36b-1287-4d5b-a122-123f239b6131 \
  --env=prod \
  -- bash -c 'echo "$CLOUDFLARE_API_TOKEN" | cut -c1-8'
```

(`d231f36b-1287-4d5b-a122-123f239b6131` is the `shared-infra` workspace ID — not a secret.)

In the examples below, assume `$CLOUDFLARE_API_TOKEN` is already in env (wrap the whole script in `infisical run -- bash -c '...'` or export it in a subshell).

## Find zone ID

```bash
ZONE_NAME="example.com"
CF_ZONE=$(curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones?name=${ZONE_NAME}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['result'][0]['id'])")
echo "$CF_ZONE"
```

## Create records

### CNAME (proxied OFF for cert validation / Azure domain binding)

```bash
SUBDOMAIN="api"
TARGET="myapp.greenhill-abc.eastus.azurecontainerapps.io"

curl -s -X POST -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/$CF_ZONE/dns_records" \
  -d "{\"type\":\"CNAME\",\"name\":\"$SUBDOMAIN\",\"content\":\"$TARGET\",\"proxied\":false}"
```

### TXT (e.g. Azure `asuid.<subdomain>` verification)

```bash
curl -s -X POST -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/$CF_ZONE/dns_records" \
  -d "{\"type\":\"TXT\",\"name\":\"asuid.${SUBDOMAIN}\",\"content\":\"${VERIFICATION_ID}\"}"
```

### A record

```bash
curl -s -X POST -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/$CF_ZONE/dns_records" \
  -d "{\"type\":\"A\",\"name\":\"$SUBDOMAIN\",\"content\":\"203.0.113.42\",\"proxied\":true}"
```

## List records

```bash
curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones/$CF_ZONE/dns_records" \
  | python3 -c "import sys,json; [print(f'{r[\"type\"]:6} {r[\"name\"]:40} {r[\"content\"]}') for r in json.load(sys.stdin)['result']]"
```

## Update a record

```bash
RECORD_ID=$(curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones/$CF_ZONE/dns_records?name=${SUBDOMAIN}.${ZONE_NAME}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['result'][0]['id'])")

curl -s -X PATCH -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/$CF_ZONE/dns_records/$RECORD_ID" \
  -d '{"content":"new-target.example.com"}'
```

## Delete a record

```bash
curl -s -X DELETE -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/zones/$CF_ZONE/dns_records/$RECORD_ID"
```

## Verify propagation

```bash
dig +short CNAME ${SUBDOMAIN}.${ZONE_NAME}
dig +short TXT asuid.${SUBDOMAIN}.${ZONE_NAME}
```

## Common mistakes

| Mistake | Fix |
|---------|-----|
| `proxied: true` when binding to Azure / issuing a managed SSL cert | Set `proxied: false`. The origin server has to see the real request for domain validation. |
| Including the zone in the `name` (e.g. `api.example.com`) when creating | Cloudflare accepts both, but convention is subdomain only (`api`) — zone is implicit from the URL. |
| Wildcard TXT names | For `asuid.<sub>` records, `name` is `asuid.<sub>`, not the full FQDN. |
| Token missing Zone:DNS:Edit scope | API returns `10000 Authentication error`. Mint a new token in Cloudflare → My Profile → API Tokens. |
| Token stored in `.env` on laptops | Use `infisical run` — never write the token to a file that could be committed. |
