# Connecting a script to the Shopify Admin API

Two paths. Check which one your store offers **first**, in
`Settings -> Apps and sales channels -> App development`:

| What you see there | Use |
|---|---|
| "Create an app" button | **Path A** — 2 minutes, no OAuth |
| Only "Build apps in Dev Dashboard" | **Path B** — legacy custom apps retired on this store |

---

## Step 0 — `.gitignore` BEFORE creating any `.env`

Do this first. A repo with no `.gitignore` will happily commit your token on
the next `git add -A`.

```gitignore
.env
.env.*
!.env.example
*.pem
*.key
```

Verify it actually works, with a canary rather than by eye:

```bash
printf 'SHOPIFY_ADMIN_TOKEN=shpat_FAKE_CANARY\n' > .env
git check-ignore -v .env          # must print a .gitignore line
git status --porcelain | grep .env # must print nothing
```

---

## Path A — store still has "Develop apps"

`Settings -> Apps and sales channels -> Develop apps -> Create an app`
-> Configure Admin API scopes -> **Install app** -> reveal the token.

`.env`:

```
SHOPIFY_STORE_DOMAIN=your-store.myshopify.com
SHOPIFY_ADMIN_TOKEN=shpat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SHOPIFY_API_VERSION=2025-07
```

That is all. Two required values.

**The token is shown once.** If lost, uninstall and reinstall the app to
issue a new one.

---

## Path B — Dev Dashboard app (no backend needed)

A Dev Dashboard app issues its token through OAuth to the app's *backend*.
You do not need to host one: OAuth can redirect to `localhost`, and
`scripts/get_admin_token.py` acts as that backend for about ten seconds.

### B1. Configure the app, exactly these fields

| Field | Value |
|---|---|
| App URL | `http://localhost:3456/` |
| Embed app in Shopify admin | **unchecked** |
| Scopes | the comma-separated list below |
| **Use legacy install flow** | **CHECKED** |
| Redirect URLs | `http://localhost:3456/callback` |
| Distribution | Custom distribution -> your store domain |

Scopes (trim to what you actually need):

```
read_products,write_products,read_inventory,write_inventory,read_locations,read_publications,write_publications,read_content,write_content,read_online_store_navigation,write_online_store_navigation,read_themes,write_themes
```

### B2. Press **Release**

Dev Dashboard config is versioned. Until you release, `/admin/oauth/authorize`
reads the *previous* active version and returns **403 Unauthorized Access**.

### B3. `.env.live` — three values you supply

```
SHOPIFY_STORE_DOMAIN=your-store.myshopify.com
SHOPIFY_CLIENT_ID=0e372ef6...          # 32 hex chars, no prefix
SHOPIFY_CLIENT_SECRET=shpss_...        # yes, the SECRET starts with shpss_
SHOPIFY_API_VERSION=2025-07
```

### B4. Run the helper

```bash
python3 scripts/get_admin_token.py --env .env.live
```

It prints an approval URL, captures the code on localhost, exchanges it, and
appends `SHOPIFY_ADMIN_TOKEN=shpat_...` to the same file. `grant_options[]`
is sent empty, which requests an **offline** token that does not expire.

---

## Credential types — the trap

The API credentials screen shows three values. Only one authenticates the
Admin API:

| Value | Looks like | Purpose |
|---|---|---|
| API key / Client ID | `0e372ef6...` (no prefix) | app identity |
| API secret key | **`shpss_...`** | verifying webhook HMACs |
| Admin API access token | **`shpat_...`** | **what the API needs** |

`shpss_` and `shpat_` are **both 38 characters**, so length tells you
nothing — only the prefix does. The secret key stays permanently visible
while the access token is hidden after install, which is why the wrong one
is so easy to grab. Sending `shpss_` returns:

```
HTTP 401 {"errors":"[API] Invalid API key or access token"}
```

---

## Gotchas worth pre-empting

**Domain formatting.** If you paste `https://store.myshopify.com/` the
trailing slash and scheme produce `https://https://store...`. Normalize:

```python
d = domain.strip().rstrip('/')
for p in ('https://', 'http://'):
    if d.startswith(p): d = d[len(p):]
d = d.split('/')[0]
```

**Homebrew Python has no CA bundle.** `urllib` fails with
`CERTIFICATE_VERIFY_FAILED`. Pass a bundle instead of disabling verification:

```python
ssl.create_default_context(cafile='/etc/ssl/cert.pem')   # or certifi.where()
```

**`admin.shopify.com/store/<handle>` differs from the myshopify subdomain.**
A store at `my-store.myshopify.com` may have admin handle `gpr0c5-md`. That
redirect is normal — not the wrong store.

**Be signed into the right store.** Opening the authorize URL in a tab logged
into a different store returns 403 regardless of app config.

**Ignore stale callbacks.** Restarting the helper while the browser still has
the old redirect pending delivers a callback with the previous `state`. Skip
it and keep listening; do not abort — a mismatch there is expected, not an
attack.

**Granted scopes look shorter than requested.** Shopify collapses pairs:
`write_products` implies `read_products`. Nothing is missing.

**Request least privilege.** Skip `read_customers`, `read_orders`,
`read_all_orders`, `write_draft_orders`, `read_checkouts` unless a task needs
them. On a store with real orders those are live customer PII, and a leaked
token then exposes your customer list rather than your catalogue.

---

## Verify before writing anything

```bash
curl -s -X POST "https://$DOMAIN/admin/api/2025-07/graphql.json" \
  -H "Content-Type: application/json" \
  -H "X-Shopify-Access-Token: $TOKEN" \
  -d '{"query":"query{ shop{ name myshopifyDomain plan{displayName partnerDevelopment} } }"}'
```

`partnerDevelopment: true` means a dev store. If it says `false`, you are
pointed at production — confirm that is intended.

## Multi-store safety

Keep one file per store (`.env`, `.env.live`) and give every script an
`--env` flag. Swapping a token inside a single `.env` is how an `--apply` run
ends up hitting production.

## Files to copy into the new project

- `scripts/get_admin_token.py` — the localhost OAuth helper (Path B only)
- `.env.example` — committed template, no real values
- the `.gitignore` block from Step 0
