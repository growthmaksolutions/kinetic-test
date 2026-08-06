#!/usr/bin/env python3
"""
Phase 2 + Phase 4 — add custom.fitment_data and custom.spec_rows to the LIVE
store's existing products.

Scope, enforced by construction rather than by care:

  * The ONLY mutations here are metafieldDefinitionCreate and metafieldsSet.
    productCreate / productDelete / productUpdate / productSet / productVariants*
    do not appear in this file, so no product can be created, deleted, or have
    its price, SKU, handle, images, variants or description altered.
  * metafieldsSet writes only the two named keys. Every other metafield on the
    product is left untouched.

Values are derived from each live product's OWN custom.fitment and
custom.specifications, so nothing is matched across stores and a value can
never be attached to the wrong product.

  python3 scripts/migrate_live_metafields.py --define          # Phase 2, dry
  python3 scripts/migrate_live_metafields.py --define --apply
  python3 scripts/migrate_live_metafields.py --limit 25         # Phase 4, dry
  python3 scripts/migrate_live_metafields.py --limit 25 --apply
  python3 scripts/migrate_live_metafields.py --apply            # remainder
"""
import argparse, importlib.util, json, os, ssl, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# reuse the audited derivation logic
_spec = importlib.util.spec_from_file_location(
    'imp', os.path.join(ROOT, 'scripts', 'import_csv_products.py'))
_imp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_imp)

TARGET_KEYS = ('fitment_data', 'spec_rows')

DEFINITIONS = [
    ("fitment_data", "Fitment data", "list.single_line_text_field",
     "One record per entry as Make|Model|Years. Drives the fitment checker."),
    ("spec_rows", "Spec rows", "list.single_line_text_field",
     "One row per entry as Label|Value. Drives the specifications table."),
]

Q_DEFS = """
query{ metafieldDefinitions(first:100, ownerType:PRODUCT, namespace:"custom"){
  nodes{ id key type{ name } } } }
"""
M_DEF = """
mutation D($definition: MetafieldDefinitionInput!){
  metafieldDefinitionCreate(definition:$definition){
    createdDefinition{ id key } userErrors{ field message code } } }
"""
Q_PRODUCTS = """
query($c:String){ products(first:100, after:$c){ nodes{ id handle title
  metafields(first:30, namespace:"custom"){ nodes{ key value } } }
  pageInfo{ hasNextPage endCursor } } }
"""
M_SET = """
mutation S($metafields:[MetafieldsSetInput!]!){
  metafieldsSet(metafields:$metafields){
    metafields{ key owner{ ... on Product { id handle } } }
    userErrors{ field message code } } }
"""


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

    def call(self, q, v=None, retries=5):
        for attempt in range(retries):
            b = json.dumps({"query": q, "variables": v or {}}).encode()
            r = urllib.request.Request(self.url, data=b, method='POST', headers={
                'Content-Type': 'application/json', 'X-Shopify-Access-Token': self.tok})
            try:
                with urllib.request.urlopen(r, timeout=90, context=self.ctx) as resp:
                    p = json.loads(resp.read())
            except urllib.error.HTTPError as ex:
                if ex.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                    time.sleep(2 * (attempt + 1)); continue
                raise SystemExit(f"HTTP {ex.code}: {ex.read().decode(errors='replace')[:250]}")
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as ex:
                if attempt < retries - 1:
                    time.sleep(3 * (attempt + 1)); continue
                raise SystemExit(f"connection failed: {ex!r}")
            if p.get('errors'):
                msg = json.dumps(p['errors'])
                if 'THROTTLED' in msg and attempt < retries - 1:
                    time.sleep(2 * (attempt + 1)); continue
                raise SystemExit("GraphQL: " + msg[:350])
            return p['data']


def derive(product):
    """Build the two values from this product's own metafields."""
    mf = {m['key']: m['value'] for m in product['metafields']['nodes']}
    row = {_imp.MF_MODEL: mf.get('model', ''),
           _imp.MF_FIT: mf.get('fitment', ''),
           _imp.MF_SPEC: mf.get('specifications', ''),
           'Title': product.get('title', '')}
    return _imp.parse_fitment_data(row), _imp.parse_spec_rows(mf.get('specifications', ''))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--env', default=os.path.join(ROOT, '.env.live'))
    ap.add_argument('--apply', action='store_true', help='write (default: dry run)')
    ap.add_argument('--define', action='store_true', help='Phase 2 only: create definitions')
    ap.add_argument('--limit', type=int, default=0, help='only process the first N products')
    ap.add_argument('--batch', type=int, default=25, help='products per batch')
    ap.add_argument('--log', default=os.path.join(ROOT, 'backups', 'live-write-log.jsonl'))
    args = ap.parse_args()

    shop = Shop(load_env(args.env))
    info = shop.call("query{ shop{ name myshopifyDomain } }")['shop']
    print(f"store : {info['name']} ({info['myshopifyDomain']})")
    print(f"mode  : {'APPLY' if args.apply else 'DRY RUN'}\n")

    existing = {d['key']: d for d in shop.call(Q_DEFS)['metafieldDefinitions']['nodes']}

    if args.define:
        print("PHASE 2 — metafield definitions")
        for key, name, mtype, desc in DEFINITIONS:
            if key in existing:
                print(f"  custom.{key:16s} already exists ({existing[key]['type']['name']})")
                continue
            if not args.apply:
                print(f"  custom.{key:16s} WOULD CREATE  {mtype}")
                continue
            res = shop.call(M_DEF, {"definition": {
                "name": name, "namespace": "custom", "key": key,
                "type": mtype, "ownerType": "PRODUCT", "description": desc}})['metafieldDefinitionCreate']
            print(f"  custom.{key:16s} " +
                  ("created" if res['createdDefinition'] else str(res['userErrors'])))
        return

    for key, _, mtype, _ in DEFINITIONS:
        if key not in existing:
            raise SystemExit(f"custom.{key} definition missing — run --define --apply first")
        if existing[key]['type']['name'] != mtype:
            raise SystemExit(f"custom.{key} is {existing[key]['type']['name']}, expected {mtype}")

    products, cur = [], None
    while True:
        p = shop.call(Q_PRODUCTS, {"c": cur})['products']
        products.extend(p['nodes'])
        if not p['pageInfo']['hasNextPage']:
            break
        cur = p['pageInfo']['endCursor']

    todo = []
    skipped_done = 0
    for prod in products:
        have = {m['key'] for m in prod['metafields']['nodes']}
        if all(k in have for k in TARGET_KEYS):
            skipped_done += 1
            continue
        fit, spec = derive(prod)
        fields = []
        if fit and 'fitment_data' not in have:
            fields.append(("fitment_data", json.dumps(fit), len(fit)))
        if spec and 'spec_rows' not in have:
            fields.append(("spec_rows", json.dumps(spec), len(spec)))
        if fields:
            todo.append((prod, fields))

    if args.limit:
        todo = todo[:args.limit]

    print(f"PHASE 4 — products needing the two metafields: {len(todo)}"
          f"   (already complete: {skipped_done})")
    if not args.apply:
        for prod, fields in todo[:8]:
            desc = "  ".join(f"{k}={n}" for k, _, n in fields)
            print(f"  would set  {prod['handle'][:52]:54s} {desc}")
        if len(todo) > 8:
            print(f"  ... and {len(todo)-8} more")
        print("\nre-run with --apply to write")
        return

    os.makedirs(os.path.dirname(args.log), exist_ok=True)
    logf = open(args.log, 'a', encoding='utf-8')
    ok = fail = 0
    for start in range(0, len(todo), args.batch):
        chunk = todo[start:start + args.batch]
        payload, index = [], []
        for prod, fields in chunk:
            for key, value, n in fields:
                payload.append({"ownerId": prod['id'], "namespace": "custom",
                                "key": key, "type": "list.single_line_text_field",
                                "value": value})
                index.append((prod, key, n))
        # metafieldsSet accepts at most 25 metafields per call
        for i in range(0, len(payload), 25):
            sub = payload[i:i + 25]
            res = shop.call(M_SET, {"metafields": sub})['metafieldsSet']
            errs = res['userErrors']
            if errs:
                fail += len(sub)
                print(f"  FAIL batch@{start}: {errs[:2]}")
                logf.write(json.dumps({"ts": time.strftime('%Y-%m-%dT%H:%M:%S'),
                                       "action": "metafieldsSet", "status": "error",
                                       "errors": errs[:3], "count": len(sub)}) + "\n")
                logf.flush()
                raise SystemExit("stopping — resolve before continuing")
            ok += len(res['metafields'])
        for prod, key, n in index:
            logf.write(json.dumps({
                "ts": time.strftime('%Y-%m-%dT%H:%M:%S'),
                "action": "metafieldsSet", "status": "ok",
                "product_id": prod['id'], "handle": prod['handle'],
                "namespace": "custom", "key": key,
                "before": None, "entries_after": n,
                "fields_untouched": "price,sku,handle,images,variants,description",
            }) + "\n")
        logf.flush()
        done = min(start + args.batch, len(todo))
        print(f"  batch {start//args.batch + 1:>3}  products {done}/{len(todo)}  metafields written={ok}")
    logf.close()
    print(f"\nmetafields written: {ok}   failed: {fail}")
    print(f"log: {args.log}")


if __name__ == '__main__':
    main()
