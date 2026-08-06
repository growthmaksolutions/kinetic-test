#!/usr/bin/env python3
"""
Phase 0 — full read-only backup of the live store.

Writes a timestamped directory containing everything the current token can
read, plus a manifest recording what could NOT be captured and why, so the
gaps are visible rather than silently missing.

Read-only: this script issues no mutations. Theme duplication (the other
Phase 0 item) is a separate, explicit step.

  python3 scripts/backup_live.py --env .env.live --out backups
"""
import argparse, base64, json, os, ssl, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ssl_ctx():
    for p in ('/etc/ssl/cert.pem', '/opt/homebrew/etc/openssl@3/cert.pem'):
        if os.path.exists(p):
            return ssl.create_default_context(cafile=p)
    return ssl.create_default_context()


def load_env(path):
    e = {}
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            e[k.strip()] = v.strip().strip('"').strip("'")
    return e


class Shop:
    def __init__(self, env):
        d = env['SHOPIFY_STORE_DOMAIN'].replace('https://', '').replace('http://', '').rstrip('/')
        self.domain = d.split('/')[0]
        self.url = f"https://{self.domain}/admin/api/{env.get('SHOPIFY_API_VERSION','2025-07')}/graphql.json"
        self.tok = env['SHOPIFY_ADMIN_TOKEN']
        self.ctx = ssl_ctx()
        self.denied = []

    def call(self, q, v=None, label=''):
        for attempt in range(4):
            b = json.dumps({"query": q, "variables": v or {}}).encode()
            r = urllib.request.Request(self.url, data=b, method='POST', headers={
                'Content-Type': 'application/json', 'X-Shopify-Access-Token': self.tok})
            try:
                with urllib.request.urlopen(r, timeout=90, context=self.ctx) as resp:
                    p = json.loads(resp.read())
            except (urllib.error.HTTPError, urllib.error.URLError, OSError) as ex:
                if attempt < 3:
                    time.sleep(2 * (attempt + 1)); continue
                self.denied.append((label, f'network: {ex!r}')); return None
            if p.get('errors'):
                msg = json.dumps(p['errors'])
                if 'THROTTLED' in msg and attempt < 3:
                    time.sleep(2 * (attempt + 1)); continue
                self.denied.append((label, msg[:180])); return None
            return p['data']
        return None

    def paged(self, q, root, label):
        out, cur = [], None
        while True:
            d = self.call(q, {"c": cur}, label)
            if not d:
                return out
            node = d[root]
            out.extend(node['nodes'])
            if not node['pageInfo']['hasNextPage']:
                return out
            cur = node['pageInfo']['endCursor']


Q_PRODUCTS = """
query($c:String){ products(first:100, after:$c){ nodes{
  id handle title status vendor productType tags createdAt updatedAt publishedAt
  descriptionHtml
  seo{ title description }
  featuredMedia{ preview{ image{ url } } }
  mediaCount{ count }
  media(first:250){ nodes{ ... on MediaImage { id image{ url altText } } } }
  options{ name position optionValues{ name } }
  variants(first:250){ nodes{ id title sku barcode price compareAtPrice position
     inventoryPolicy inventoryQuantity
     inventoryItem{ id tracked requiresShipping measurement{ weight{ value unit } } } } }
  metafields(first:50){ nodes{ namespace key type value definition{ id } } }
} pageInfo{ hasNextPage endCursor } } }
"""
Q_COLLECTIONS = """
query($c:String){ collections(first:100, after:$c){ nodes{
  id handle title descriptionHtml sortOrder templateSuffix
  productsCount{ count }
  ruleSet{ appliedDisjunctively rules{ column relation condition } }
  metafields(first:25){ nodes{ namespace key type value } }
} pageInfo{ hasNextPage endCursor } } }
"""
Q_REDIRECTS = """
query($c:String){ urlRedirects(first:250, after:$c){ nodes{ id path target }
  pageInfo{ hasNextPage endCursor } } }
"""
Q_PAGES = """
query($c:String){ pages(first:100, after:$c){ nodes{ id handle title templateSuffix isPublished body }
  pageInfo{ hasNextPage endCursor } } }
"""
Q_MENUS = """
query{ menus(first:50){ nodes{ id handle title
  items{ id title type url tags
    items{ id title type url items{ id title type url } } } } } }
"""
Q_THEMES = "query{ themes(first:50){ nodes{ id name role createdAt updatedAt } } }"
Q_THEME_FILES = """
query($id:ID!, $c:String){ theme(id:$id){ name role
  files(first:100, after:$c){ nodes{ filename size
    body{ ... on OnlineStoreThemeFileBodyText { content }
          ... on OnlineStoreThemeFileBodyBase64 { contentBase64 }
          ... on OnlineStoreThemeFileBodyUrl { url } } }
    pageInfo{ hasNextPage endCursor } } } }
"""
DEF_OWNERS = ['PRODUCT', 'PRODUCTVARIANT', 'COLLECTION', 'CUSTOMER', 'ORDER', 'PAGE', 'SHOP']
Q_DEFS = """
query($o:MetafieldOwnerType!, $c:String){ metafieldDefinitions(first:100, ownerType:$o, after:$c){
  nodes{ id name namespace key description type{ name } ownerType
         useAsCollectionCondition validations{ name value } }
  pageInfo{ hasNextPage endCursor } } }
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--env', default=os.path.join(ROOT, '.env.live'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'backups'))
    ap.add_argument('--stamp', required=True, help='date stamp, e.g. 2026-08-06')
    ap.add_argument('--theme-code', action='store_true', help='also pull full theme file bodies')
    args = ap.parse_args()

    env = load_env(args.env)
    shop = Shop(env)
    info = shop.call("query{ shop{ name myshopifyDomain currencyCode ianaTimezone "
                     "plan{ displayName partnerDevelopment } } }", label='shop')
    if not info:
        raise SystemExit('cannot reach the store: ' + json.dumps(shop.denied)[:300])
    s = info['shop']

    outdir = os.path.join(args.out, f"live-{s['myshopifyDomain'].split('.')[0]}-{args.stamp}")
    os.makedirs(outdir, exist_ok=True)
    print(f"store  : {s['name']} ({s['myshopifyDomain']})  plan={s['plan']['displayName']}")
    print(f"output : {outdir}\n")

    def dump(name, obj):
        p = os.path.join(outdir, name)
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump(obj, fh, indent=2, ensure_ascii=False)
        n = len(obj) if isinstance(obj, list) else 1
        print(f"  {name:34s} {n:5d} record(s)  {os.path.getsize(p)/1024:8.1f} KB")
        return n

    dump('shop.json', s)

    products = shop.paged(Q_PRODUCTS, 'products', 'products')
    dump('products.json', products)

    defs = []
    for owner in DEF_OWNERS:
        cur = None
        while True:
            d = shop.call(Q_DEFS, {"o": owner, "c": cur}, f'definitions:{owner}')
            if not d:
                break
            node = d['metafieldDefinitions']
            defs.extend(node['nodes'])
            if not node['pageInfo']['hasNextPage']:
                break
            cur = node['pageInfo']['endCursor']
    dump('metafield_definitions.json', defs)

    dump('collections.json', shop.paged(Q_COLLECTIONS, 'collections', 'collections'))
    dump('url_redirects.json', shop.paged(Q_REDIRECTS, 'urlRedirects', 'redirects'))
    dump('pages.json', shop.paged(Q_PAGES, 'pages', 'pages'))

    menus = shop.call(Q_MENUS, label='menus')
    dump('menus.json', (menus or {}).get('menus', {}).get('nodes', []))

    themes = shop.call(Q_THEMES, label='themes')
    tlist = (themes or {}).get('themes', {}).get('nodes', [])
    dump('themes.json', tlist)

    # Full code of the published theme — the rollback source of truth.
    if args.theme_code:
        main_theme = next((t for t in tlist if t['role'] == 'MAIN'), None)
        if main_theme:
            tdir = os.path.join(outdir, 'theme-main-files')
            os.makedirs(tdir, exist_ok=True)
            cur, count = None, 0
            while True:
                d = shop.call(Q_THEME_FILES, {"id": main_theme['id'], "c": cur}, 'theme files')
                if not d or not d.get('theme'):
                    break
                fnode = d['theme']['files']
                for f in fnode['nodes']:
                    body = f.get('body') or {}
                    content = body.get('content')
                    if content is None and body.get('contentBase64'):
                        try:
                            content = base64.b64decode(body['contentBase64']).decode('utf-8', 'replace')
                        except Exception:
                            content = None
                    if content is None:
                        continue
                    dest = os.path.join(tdir, f['filename'])
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, 'w', encoding='utf-8') as fh:
                        fh.write(content)
                    count += 1
                if not fnode['pageInfo']['hasNextPage']:
                    break
                cur = fnode['pageInfo']['endCursor']
            print(f"  theme-main-files/                  {count:5d} file(s)  "
                  f"[{main_theme['name']}]")

    manifest = {
        "captured_at": args.stamp,
        "store": {"name": s['name'], "domain": s['myshopifyDomain'],
                  "plan": s['plan']['displayName'], "currency": s['currencyCode']},
        "counts": {
            "products": len(products),
            "metafield_definitions": len(defs),
        },
        "read_only": True,
        "not_captured": [
            {"item": "customers", "reason": "token has no read_customers scope (deliberate — PII)"},
            {"item": "orders", "reason": "token has no read_orders scope (deliberate — PII)"},
            {"item": "policies", "reason": "requires read_legal_policies scope"},
            {"item": "installed apps", "reason": "requires read_apps scope"},
            {"item": "web pixels", "reason": "requires read_pixels scope"},
        ],
        "errors": [{"label": a, "detail": b} for a, b in shop.denied],
    }
    with open(os.path.join(outdir, 'MANIFEST.json'), 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=2)
    print(f"\n  MANIFEST.json written")
    if shop.denied:
        print(f"\n  {len(shop.denied)} query error(s) recorded in the manifest:")
        for a, b in shop.denied[:8]:
            print(f"    {a}: {b[:110]}")


if __name__ == '__main__':
    main()
