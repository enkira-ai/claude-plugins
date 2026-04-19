---
name: setup-repo-account
description: Use when the user wants to configure a git repo to commit and push using a specific GitHub account, set up a new GitHub account SSH key, or prevent commits being attributed to the wrong GitHub user.
---

# Setup Repo GitHub Account

Configure a local git repository so all commits and pushes use a specific GitHub account — regardless of the global git config.

Two mechanisms work together:
1. **Local `user.name`/`user.email`** — commits are attributed to the right person
2. **SSH host alias** — pushes authenticate as the right GitHub account

## Step-by-Step

### 1. Ask the user for the target account

Ask:
- GitHub username (e.g. `bwen-uchicago`)
- Email associated with that GitHub account
- Display name for commits (e.g. `Bo Wen`)

### 2. Check for existing SSH alias

Read `~/.ssh/config` and look for a `Host` block that:
- Has a `HostName github.com` line
- Is already set up for this account (check `IdentityFile` path or `Host` alias name)

**If a matching alias exists** — note the `Host` alias name (e.g. `uchicago-github`) and skip to step 4.

**If no alias exists** — continue to step 3.

### 3. Set up SSH key and config alias

**Check for an existing key to reuse:**
```bash
ls ~/.ssh/*.pub
```
Ask the user if any existing key belongs to this GitHub account. If yes, use it. If no:

**Generate a new key:**
```bash
ssh-keygen -t ed25519 -C "<email>" -f ~/.ssh/id_<alias>
```
Use a filename that reflects the account (e.g. `id_uchicago_github`).

**Add to `~/.ssh/config`:**
```
Host <alias>
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_<alias>
```

Choose an alias name that reflects the account (e.g. `uchicago-github`, `personal-github`).

**Tell the user to add the public key to GitHub:**
```bash
cat ~/.ssh/id_<alias>.pub
```
Direct them to: GitHub → Settings → SSH and GPG keys → New SSH key

**Verify the key works before proceeding:**
```bash
ssh -T git@<alias>
# Expected: Hi <username>! You've successfully authenticated...
```

### 4. Set local git config

Inside the repo:
```bash
git config user.name "<display name>"
git config user.email "<email>"
```

Verify:
```bash
git config --local user.name
git config --local user.email
```

### 5. Update the remote URL

Check the current remote:
```bash
git remote get-url origin
```

If it uses `git@github.com:` — replace with the alias:
```bash
# Before: git@github.com:org/repo.git
# After:  git@<alias>:org/repo.git
git remote set-url origin git@<alias>:<org>/<repo>.git
```

If it uses `https://` — switch to SSH with the alias:
```bash
git remote set-url origin git@<alias>:<org>/<repo>.git
```

Verify the push works:
```bash
git push --dry-run
```

### 6. Confirm setup

Show the user a summary:
```
Repo configured for: <display name> <email>
SSH alias:           <alias> → github.com (key: ~/.ssh/id_<alias>)
Remote URL:          git@<alias>:<org>/<repo>.git
Local git config:    user.name / user.email set
```

## Quick Reference

| Problem | Fix |
|---------|-----|
| Wrong author on commits | `git config user.name` / `git config user.email` (local, not global) |
| Push authenticates as wrong account | Update remote URL to use SSH alias |
| No SSH key for account | `ssh-keygen -t ed25519 -C email -f ~/.ssh/id_alias` |
| Verify which account SSH uses | `ssh -T git@<alias>` |
| Check current remote | `git remote get-url origin` |

## Common Mistakes

- **Setting config globally** (`--global`) — affects all repos. Use local (no flag) for per-repo override.
- **Forgetting to update the remote URL** — local config fixes commit authorship but pushes still authenticate via the old SSH key.
- **Using `git@github.com:` after adding an alias** — the alias only works if the remote URL actually uses it.
- **Key not added to GitHub** — `ssh -T` will fail with "Permission denied (publickey)"; add the `.pub` key to GitHub settings first.
