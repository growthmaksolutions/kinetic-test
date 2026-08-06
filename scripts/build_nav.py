#!/usr/bin/env python3
"""
Build the store's collections and navigation to match the imported catalogue.

Collections are SMART, keyed on the custom.model and custom.product_category
metafield definitions, so they keep themselves current as products are added
or re-categorised — nothing here needs re-running for new stock.

The menus follow the contract in sections/header.liquid + header-megamenu:
  * a top-level item titled "Shop" with children renders as the mega menu
  * each mega column title is handleized and looked up as its own menu
    (linklists[handle]); nested children are the fallback
so the columns are built as nested items, which need no extra menus.

  python3 scripts/build_nav.py            # dry run
  python3 scripts/build_nav.py --apply
"""
import argparse, json, os, ssl, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (handle, title, [metafield values]) — several values are OR-ed together so
# near-duplicate category names collapse into one shopper-facing collection.
MODELS = [
    ('sportster', 'Sportster', ['Sportster']),
    ('softail',   'Softail',   ['Softail']),
    ('dyna',      'Dyna',      ['Dyna']),
    ('triumph',   'Triumph',   ['Triumph', 'Bonneville']),
    ('honda',     'Honda',     ['Honda']),
    ('indian',    'Indian',    ['Indian']),
]

CATEGORIES = [
    ('exhausts',              'Exhausts',              ['Exhausts', 'Mufflers & Exhaust']),
    ('intake-systems',        'Intake Systems',        ['Intake Systems', 'Intake']),
    ('handlebars',            'Handlebars',            ['Handlebars']),
    ('grips',                 'Grips',                 ['Grips']),
    ('footpegs-and-shifters', 'Footpegs & Shifters',   ['Footpegs and Shifters']),
    ('controls',              'Controls',              ['Controls']),
    ('electrical',            'Electrical',            ['Electrical']),
    ('lighting',              'Lighting',              ['Lighting']),
    ('suspension-and-chassis','Suspension & Chassis',  ['Suspension and Chassis']),
    ('covers-and-armor',      'Covers & Armor',        ['Covers-Decals-Armor', 'Faceplates']),
    ('accessories',           'Accessories',           ['Accessories']),
    ('apparel',               'Apparel',               ['Apparel', 'Lifestyle']),
    ('decals-and-pins',       'Decals & Pins',         ['Decals & Patches', 'Magnets & Pins']),
]

MUT_COLLECTION = """
mutation MakeCollection($input: CollectionInput!) {
  collectionCreate(input: $input) {
    collection { id handle title }
    userErrors { field message }
  }
}
"""
QUERY_COLLECTIONS = """
query($c: String) {
  collections(first: 250, after: $c) {
    nodes { id handle }
    pageInfo { hasNextPage endCursor }
  }
}
"""
QUERY_DEFS = """
query { metafieldDefinitions(first: 30, ownerType: PRODUCT, namespace: "custom") {
  nodes { id key useAsCollectionCondition } } }
"""
QUERY_MENUS = "query { menus(first: 20) { nodes { id handle title } } }"
MUT_MENU_UPDATE = """
mutation UpdateMenu($id: ID!, $title: String!, $handle: String!, $items: [MenuItemUpdateInput!]!) {
  menuUpdate(id: $id, title: $title, handle: $handle, items: $items) {
    menu { id handle }
    userErrors { field message }
  }
}
"""
MUT_MENU_CREATE = """
mutation CreateMenu($title: String!, $handle: String!, $items: [MenuItemCreateInput!]!) {
  menuCreate(title: $title, handle: $handle, items: $items) {
    menu { id handle }
    userErrors { field message }
  }
}
"""


def ssl_context():
    for p in ('/etc/ssl/cert.pem', '/opt/homebrew/etc/openssl@3/cert.pem'):
        if os.path.exists(p):
            return ssl.create_default_context(cafile=p)
    return ssl.create_default_context()


class Shop:
    def __init__(self, domain, token, version='2025-07'):
        d = domain.strip().rstrip('/')
        for p in ('https://', 'http://'):
            if d.startswith(p):
                d = d[len(p):]
        self.url = f"https://{d.split('/')[0]}/admin/api/{version}/graphql.json"
        self.token = token
        self.ctx = ssl_context()

    def call(self, q, v=None):
        b = json.dumps({"query": q, "variables": v or {}}).encode()
        r = urllib.request.Request(self.url, data=b, method='POST', headers={
            'Content-Type': 'application/json', 'X-Shopify-Access-Token': self.token})
        try:
            with urllib.request.urlopen(r, timeout=60, context=self.ctx) as resp:
                p = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise SystemExit(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
        if p.get('errors'):
            raise SystemExit("GraphQL: " + json.dumps(p['errors'])[:400])
        return p['data']


def load_env(path):
    env = {}
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--env', default=os.path.join(ROOT, '.env'))
    args = ap.parse_args()

    env = load_env(args.env)
    shop = Shop(env['SHOPIFY_STORE_DOMAIN'], env['SHOPIFY_ADMIN_TOKEN'],
                env.get('SHOPIFY_API_VERSION') or '2025-07')

    defs = {n['key']: n for n in shop.call(QUERY_DEFS)['metafieldDefinitions']['nodes']}
    for k in ('model', 'product_category'):
        if k not in defs:
            raise SystemExit(f"custom.{k} definition missing")
        if not defs[k]['useAsCollectionCondition']:
            raise SystemExit(f"custom.{k} needs useAsCollectionCondition=true")

    existing, cur = {}, None
    while True:
        page = shop.call(QUERY_COLLECTIONS, {"c": cur})['collections']
        existing.update({n['handle']: n['id'] for n in page['nodes']})
        if not page['pageInfo']['hasNextPage']:
            break
        cur = page['pageInfo']['endCursor']

    plan = ([(h, t, vals, defs['model']['id'], 'model') for h, t, vals in MODELS]
            + [(h, t, vals, defs['product_category']['id'], 'category')
               for h, t, vals in CATEGORIES])

    print(f"mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print(f"existing collections: {len(existing)}\n")

    made = 0
    for handle, title, values, def_id, kind in plan:
        if handle in existing:
            print(f"  exists  {handle:24s} {title}")
            continue
        if not args.apply:
            print(f"  create  {handle:24s} {title:22s} ({kind}: {', '.join(values)})")
            made += 1
            continue
        rules = [{"column": "PRODUCT_METAFIELD_DEFINITION", "relation": "EQUALS",
                  "condition": v, "conditionObjectId": def_id} for v in values]
        res = shop.call(MUT_COLLECTION, {"input": {
            "handle": handle, "title": title,
            "ruleSet": {"appliedDisjunctively": True, "rules": rules},
        }})['collectionCreate']
        if res['userErrors']:
            print(f"  FAIL    {handle:24s} {res['userErrors']}")
            continue
        existing[handle] = res['collection']['id']
        made += 1
        print(f"  created {handle:24s} {title}")

    print(f"\ncollections {'created' if args.apply else 'to create'}: {made}")

    if not args.apply:
        return

    # ---- navigation ----------------------------------------------------
    def col(h):
        return {"title": None, "url": f"/collections/{h}"}

    shop_children = [
        {"title": "Shop by model", "type": "HTTP", "url": "/collections/all",
         "items": [{"title": t, "type": "COLLECTION_LINK" if h in existing else "HTTP",
                    "url": f"/collections/{h}"} for h, t, _ in MODELS]},
        {"title": "Parts & accessories", "type": "HTTP", "url": "/collections/all",
         "items": [{"title": t, "type": "COLLECTION_LINK" if h in existing else "HTTP",
                    "url": f"/collections/{h}"} for h, t, _ in CATEGORIES[:7]]},
        {"title": "Gear & extras", "type": "HTTP", "url": "/collections/all",
         "items": [{"title": t, "type": "COLLECTION_LINK" if h in existing else "HTTP",
                    "url": f"/collections/{h}"} for h, t, _ in CATEGORIES[7:]]},
    ]

    main_items = [
        {"title": "Shop", "type": "HTTP", "url": "/collections/all", "items": shop_children},
        {"title": "Models", "type": "HTTP", "url": "/collections/all",
         "items": [{"title": t, "type": "HTTP", "url": f"/collections/{h}"} for h, t, _ in MODELS]},
        {"title": "About", "type": "HTTP", "url": "/pages/about"},
        {"title": "Reviews", "type": "HTTP", "url": "/pages/reviews"},
        {"title": "Contact", "type": "HTTP", "url": "/pages/contact-us"},
    ]

    footer_items = [
        {"title": "Shop", "type": "HTTP", "url": "/collections/all",
         "items": [{"title": t, "type": "HTTP", "url": f"/collections/{h}"}
                   for h, t, _ in CATEGORIES[:6]]},
        {"title": "Models", "type": "HTTP", "url": "/collections/all",
         "items": [{"title": t, "type": "HTTP", "url": f"/collections/{h}"} for h, t, _ in MODELS]},
        {"title": "Company", "type": "HTTP", "url": "/pages/about",
         "items": [
             {"title": "About", "type": "HTTP", "url": "/pages/about"},
             {"title": "Reviews", "type": "HTTP", "url": "/pages/reviews"},
             {"title": "FAQ", "type": "HTTP", "url": "/pages/faq"},
             {"title": "Contact", "type": "HTTP", "url": "/pages/contact-us"},
         ]},
        {"title": "Help", "type": "HTTP", "url": "/search",
         "items": [
             {"title": "Search", "type": "HTTP", "url": "/search"},
             {"title": "All products", "type": "HTTP", "url": "/collections/all"},
         ]},
    ]

    def strip_types(items):
        """menuUpdate rejects COLLECTION_LINK without a resourceId, so send
        plain HTTP links — the URL is what the theme renders anyway."""
        out = []
        for i in items:
            n = {"title": i["title"], "type": "HTTP", "url": i["url"]}
            if i.get("items"):
                n["items"] = strip_types(i["items"])
            out.append(n)
        return out

    menus = {m['handle']: m['id'] for m in shop.call(QUERY_MENUS)['menus']['nodes']}
    for handle, title, items in (('main-menu', 'Main menu', main_items),
                                 ('footer', 'Footer menu', footer_items)):
        payload = strip_types(items)
        if handle in menus:
            res = shop.call(MUT_MENU_UPDATE, {"id": menus[handle], "title": title,
                                              "handle": handle, "items": payload})['menuUpdate']
        else:
            res = shop.call(MUT_MENU_CREATE, {"title": title, "handle": handle,
                                              "items": payload})['menuCreate']
        errs = res['userErrors']
        print(f"  menu {handle:12s} {'updated' if not errs else errs}")


if __name__ == '__main__':
    main()
