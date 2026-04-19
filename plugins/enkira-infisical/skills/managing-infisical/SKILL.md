---
name: managing-infisical
description: Use when adding, updating, deleting, auditing, or exporting Infisical secrets in any Enkira org project (panbot, sally, shared-infra, etc.). Use when pulling API keys a skill needs before it can run. Use when onboarding a new repo to Infisical.
---

# Managing Infisical Secrets (Enkira org)

Centralized secret management for every Enkira repo. Secrets are **never** shared as `.env` files — each teammate runs `infisical login` once (SSO), and the CLI pulls secrets at runtime.

## One-time setup per teammate

```bash
infisical login    # opens browser, SSO. Token persists in OS keyring.
```

No `infisical.env`, no static client ID/secret. Admin grants org membership through the Infisical UI.

## Per-repo binding (`.infisical.json`)

Each repo links to ONE Infisical project via `.infisical.json`:

```json
{
  "workspaceId": "<project-uuid>",
  "defaultEnvironment": "dev"
}
```

Generate interactively with `infisical init` (inside the repo) or hand-write it. Commit this file — it contains no secrets, just a pointer.

### Enkira project registry

| Project | Workspace ID | Used by |
|---------|-------------|---------|
| `panbot` | check `.infisical.json` in panbot repo | panbot backend, agent, desktop, web |
| `sally`  | check `.infisical.json` in sally repo  | Sally agent |
| `shared-infra` | `d231f36b-1287-4d5b-a122-123f239b6131` | Org-wide infra secrets: Cloudflare, Azure SP, etc. Consumed by `enkira-cloudflare-dns` + `enkira-azure-containerapp` skills. |

## MANDATORY: Pull context before any mutation

Before adding, updating, or deleting ANY secret, pull current state first. Do not rely on memory.

```bash
# 1. See every secret in an env (pick the right env)
infisical export --env=dev --format=dotenv
infisical export --env=staging --format=dotenv
infisical export --env=prod --format=dotenv

# 2. Check if a key already exists
infisical export --env=dev | grep KEY_NAME
```

**Why:** past incidents where agents created duplicate keys in the wrong folder or overwrote prod with dev values. Pulling first prevents both.

## Environment independence

`dev`, `staging`, `prod` are fully independent. Updating `dev` does NOT affect `staging` or `prod`. Each env typically has DIFFERENT values for the same key (e.g. `POSTGRES_HOST` is `localhost` in dev, a cluster DNS in staging, an Azure FQDN in prod). Never blindly copy one env to another.

## Safety rules

1. **Each key lives in exactly ONE folder per env.** Duplicates across folders cause "which one wins" bugs. If you find a duplicate, delete the one in the wrong folder.
2. **Always specify `--env` explicitly.** CLI defaults to `dev` — never rely on defaults for staging/prod.
3. **`infisical secrets set` upserts.** If the key already exists in that env/path, the value is overwritten. Preview first.
4. **After any mutation, verify** — run `infisical export --env=<env>` and confirm the change landed where you intended.
5. **Placeholders:** for a new key the user will fill later, use the literal string `<SET-ME>` as the value. The CLI rejects empty strings; `<SET-ME>` is greppable and obvious in the UI.

## Common operations

### Read (export)

```bash
infisical export --env=prod --format=dotenv       # Shell-friendly
infisical export --env=prod --format=json         # JSON
infisical export --env=prod --path=/database/     # Specific folder
```

### Write (upsert)

```bash
infisical secrets set KEY=value ANOTHER=value2 --env=dev --path=/
```

Or batch from file:
```bash
infisical secrets set --file=./new_secrets.env --env=dev --path=/
```

### Delete

```bash
infisical secrets delete KEY_NAME --env=dev --path=/ --type=shared
```

The `--type=shared` flag is mandatory for deletions — default is `personal`, which will 404 for normal secrets.

### Inject into a subprocess (no files on disk) — PREFERRED

```bash
infisical run --env=prod -- ./my-script.sh
infisical run --env=prod --path=/cloud/ -- terraform apply
```

This is the preferred pattern for every skill that needs a secret at runtime. **No value is ever written to disk.** Skills in this marketplace (`enkira-cloudflare-dns`, `enkira-azure-containerapp`) all use this pattern — they do NOT consume a `.env` file.

### Writing an `.env` file (only when you must)

Some tools require a literal `.env` file (Docker Compose, some frameworks' dev servers). Only then:

```bash
infisical export --env=dev --format=dotenv > .env
```

Rules when you do this:
1. `.env` MUST be in `.gitignore` before the export runs. Verify: `grep '^\.env$' .gitignore`.
2. Delete the file as soon as the tool that needs it exits.
3. Never commit it — audit with `git status` before every commit.

Prefer `infisical run` whenever the tool accepts env vars (most do).

### Cross-project fetch

Some skills need secrets from a different project than the one `.infisical.json` points to (e.g. `enkira-cloudflare-dns` in a panbot repo needs to read `shared-infra`). Pass `--projectId`:

```bash
infisical export \
  --projectId=d231f36b-1287-4d5b-a122-123f239b6131 \
  --env=prod \
  --format=dotenv
```

## Folder + tag conventions

Folders separate secrets by concern. Tags mark which consumer uses them (so `make sync-env` can pull the right subset).

Common folders (project-dependent — check the project's own README or audit output):

| Folder | Typical contents |
|--------|-----------------|
| `/database/` | Postgres, Redis |
| `/auth/` | JWT, OAuth, OIDC |
| `/ai/` | LLM, STT, TTS, observability |
| `/cloud/` | Azure, AWS, Cloudflare, deployment infra |
| `/app/` | General app config (non-secret-ish env vars) |

Tags: usually one of `api`, `agent`, `web`, `desktop`, `worker`, `ci-cd`. Apply via `--tags=api,worker` on export.

## Bootstrap a brand-new repo

1. Admin creates a new Infisical project in the Enkira org (web UI, takes 30s).
2. Grant teammates access via project members (SSO — no creds shared).
3. In the repo:
   ```bash
   infisical init           # pick org + project, writes .infisical.json
   git add .infisical.json && git commit
   ```
4. Add secrets (see "Write" above). Start with placeholders (`<SET-ME>`) if values aren't ready; fill via web UI later.

## Audit checklist

After any mutation, or periodically:

1. **Duplicates** — same key in multiple folders within an env. Export each folder separately and diff.
2. **Empty / placeholder values** — grep export for `<SET-ME>` or blank values.
3. **Cross-env gaps** — a key present in `dev` but missing in `staging`/`prod`. Compare exports.

```bash
for env in dev staging prod; do
  echo "=== $env ==="
  infisical export --env=$env --format=dotenv | sort
done | diff <(infisical export --env=dev --format=dotenv | cut -d= -f1 | sort) \
            <(infisical export --env=prod --format=dotenv | cut -d= -f1 | sort)
```

## Checklist: adding a new secret

1. `infisical export --env=<env> | grep KEY_NAME` — confirm it doesn't already exist.
2. Pick the right folder (see table above) and tags.
3. `infisical secrets set KEY=value --env=<env> --path=/<folder>/ --tags=<tags>`.
4. Repeat for each env that needs it (with the correct per-env value).
5. Re-export and grep to confirm.
