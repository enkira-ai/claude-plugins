---
name: azure-custom-domain
description: Use when mapping a custom subdomain to an Azure Container App, setting up DNS records in Cloudflare for an Azure origin, or provisioning an Azure-managed SSL certificate. Handles the whole workflow end-to-end — FQDN lookup, DNS, ASUID verification, cert provisioning, hostname bind.
---

# Azure Container App — Custom Domain

End-to-end workflow for mapping a subdomain (in a Cloudflare-managed zone) to an Azure Container App with a managed SSL cert. Works for any Enkira-owned zone.

## Prerequisites

- `az` CLI installed + authenticated: `az login` (or `az login --service-principal ...` using creds from `shared-infra`).
- `infisical login` completed once (for Cloudflare token — see `enkira-cloudflare-dns` skill).
- The Container App already exists with external ingress enabled.

## BEFORE USE — verify subscription + SP scope

**REMIND THE USER:** `shared-infra` currently holds an Azure Service Principal that was originally created for the panbot subscription + `novaserve-ai` resource group. Before running this skill against a different subscription or RG, confirm the SP has `Contributor` (or at least Container App + DNS permissions) on your target scope:

```bash
# 1. Show the SP's current role assignments
infisical run --projectId=d231f36b-1287-4d5b-a122-123f239b6131 --env=prod -- \
  bash -c 'az login --service-principal -u "$AZURE_CLIENT_ID" -p "$AZURE_CLIENT_SECRET" --tenant "$AZURE_TENANT_ID" --only-show-errors >/dev/null && az role assignment list --assignee "$AZURE_CLIENT_ID" --all -o table'

# 2. Confirm the user intends to use THIS subscription
az account show --query "{subscription: name, id: id}" -o table
```

If the SP lacks access to your target RG/subscription, options:

1. **Preferred:** grant the shared SP the needed role on the new RG (admin action).
2. **Per-project:** mint a scoped SP (`az ad sp create-for-rbac --scopes /subscriptions/.../resourceGroups/<rg>`) and store its creds in the current repo's own Infisical project — override `AZURE_CLIENT_ID/SECRET/TENANT_ID` at that project level instead of reading from `shared-infra`.
3. **Interactive:** skip the SP and just `az login` as yourself for one-off ops — works fine outside CI.

**Do NOT silently reuse** the panbot SP against an unrelated subscription; audit logs will show panbot's identity acting on a different tenant, which makes incident review miserable.

## Inputs to gather before starting

| Variable | Example | Source |
|----------|---------|--------|
| `APP_NAME` | `myapp-prod` | Azure portal or `az containerapp list` |
| `RG` | `my-rg` | Azure resource group |
| `ENV_NAME` | `myapp-env` | `az containerapp env list -g $RG` |
| `ZONE_NAME` | `example.com` | Cloudflare zone |
| `SUBDOMAIN` | `api` | pick |

## Step 1 — fetch Container App info

```bash
FQDN=$(az containerapp show --name "$APP_NAME" --resource-group "$RG" \
  --query "properties.configuration.ingress.fqdn" -o tsv)

VERIFICATION_ID=$(az containerapp show --name "$APP_NAME" --resource-group "$RG" \
  --query "properties.customDomainVerificationId" -o tsv)

echo "FQDN: $FQDN"
echo "Verification ID: $VERIFICATION_ID"
```

If either is empty: the app doesn't have external ingress, or you're in the wrong subscription (`az account show`).

## Step 2 — create DNS records in Cloudflare

Wrap in `infisical run` so `CLOUDFLARE_API_TOKEN` lands in the subshell only:

```bash
infisical run \
  --projectId=d231f36b-1287-4d5b-a122-123f239b6131 \
  --env=prod \
  -- bash -c '
    CF_ZONE=$(curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
      "https://api.cloudflare.com/client/v4/zones?name='"$ZONE_NAME"'" \
      | python3 -c "import sys,json; print(json.load(sys.stdin)[\"result\"][0][\"id\"])")

    # CNAME — MUST be unproxied for Azure validation
    curl -s -X POST -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
      -H "Content-Type: application/json" \
      "https://api.cloudflare.com/client/v4/zones/$CF_ZONE/dns_records" \
      -d "{\"type\":\"CNAME\",\"name\":\"'"$SUBDOMAIN"'\",\"content\":\"'"$FQDN"'\",\"proxied\":false}"

    # ASUID TXT — Azure domain ownership verification
    curl -s -X POST -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
      -H "Content-Type: application/json" \
      "https://api.cloudflare.com/client/v4/zones/$CF_ZONE/dns_records" \
      -d "{\"type\":\"TXT\",\"name\":\"asuid.'"$SUBDOMAIN"'\",\"content\":\"'"$VERIFICATION_ID"'\"}"
  '
```

Verify DNS is live before touching Azure:

```bash
dig +short CNAME ${SUBDOMAIN}.${ZONE_NAME}        # should echo $FQDN
dig +short TXT asuid.${SUBDOMAIN}.${ZONE_NAME}    # should echo $VERIFICATION_ID
```

If either returns empty, wait 30–60s and retry — Cloudflare is fast but not instant.

## Step 3 — bind hostname + provision SSL

```bash
HOSTNAME="${SUBDOMAIN}.${ZONE_NAME}"
CERT_NAME="mc-$(echo "$HOSTNAME" | tr '.' '-')"

# Attach hostname (no cert yet — HTTP-only until step 3c)
az containerapp hostname add \
  --name "$APP_NAME" --resource-group "$RG" \
  --hostname "$HOSTNAME"

# Provision managed SSL cert (Azure does the ACME dance)
az containerapp env certificate create \
  --name "$ENV_NAME" --resource-group "$RG" \
  --hostname "$HOSTNAME" \
  --certificate-name "$CERT_NAME" \
  --validation-method CNAME

# Poll until Succeeded (typically 1–3 min)
while true; do
  STATE=$(az containerapp env certificate list \
    --name "$ENV_NAME" --resource-group "$RG" \
    --query "[?name=='$CERT_NAME'].properties.provisioningState" -o tsv)
  echo "cert state: $STATE"
  [ "$STATE" = "Succeeded" ] && break
  [ "$STATE" = "Failed" ] && { echo "cert provisioning failed — check CNAME + proxy setting"; exit 1; }
  sleep 15
done

# Bind cert to hostname (enables HTTPS)
az containerapp hostname bind \
  --name "$APP_NAME" --resource-group "$RG" \
  --hostname "$HOSTNAME" \
  --environment "$ENV_NAME" \
  --certificate "$CERT_NAME"
```

## Step 4 — verify

```bash
curl -fsSI "https://${HOSTNAME}/" | head -5
# Expect: HTTP/2 200 (or 3xx — any success code that proves TLS works)
```

## Rollback / teardown

```bash
# Unbind + remove hostname
az containerapp hostname remove --name "$APP_NAME" --resource-group "$RG" --hostname "$HOSTNAME" --yes

# Delete cert
az containerapp env certificate delete --name "$ENV_NAME" --resource-group "$RG" --certificate "$CERT_NAME" --yes

# Delete DNS records (see enkira-cloudflare-dns skill → "Delete a record")
```

## Common mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Cloudflare proxy enabled (`"proxied": true`) | Cert stuck in `Pending` / `Failed`; domain never validates | Set `proxied: false` |
| Missing `asuid.<sub>` TXT record | `containerapp hostname add` returns domain-ownership error | Create TXT at `asuid.<sub>` with the verification ID |
| Wrong TXT name (e.g. `asuid.sub.example.com` typed in full) | Same as above | Cloudflare adds the zone automatically; just use `asuid.<sub>` |
| Binding cert before it's `Succeeded` | `hostname bind` fails | Poll first (see loop above) |
| Wrong subscription in `az` context | FQDN / verification ID come back empty | `az account set --subscription <id>` |
