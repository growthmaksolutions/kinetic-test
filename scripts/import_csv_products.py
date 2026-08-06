#!/usr/bin/env python3
"""
Import a Shopify product-export CSV into the store via productSet, and
populate the two metafields the redesigned product page needs but which
the export does not contain:

  custom.fitment_data  list.single_line_text_field  "Make|Model|2004-2020"
  custom.spec_rows     list.single_line_text_field  "Label|Value"

Both are DERIVED from data already in the export rather than invented:

  spec_rows    <- the custom.specifications HTML, which is already a set of
                  .spec-label / .spec-value pairs.
  fitment_data <- the .fitment-grid submodels in custom.fitment, the Model
                  metafield for the family name and make, and year ranges
                  parsed from the title and the compatibility notes.

One productSet call per product carries the product, its options, all
variants, images and every metafield.

  python3 scripts/import_csv_products.py                 # dry run
  python3 scripts/import_csv_products.py --apply         # write
  python3 scripts/import_csv_products.py --apply --limit 5
"""
import argparse, csv, html, http.client, json, os, re, ssl, time
import urllib.error, urllib.request
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CURRENT_YEAR = 2026

MF_FAQS  = 'FAQs (product.metafields.custom.faqs)'
MF_FEAT  = 'Features (product.metafields.custom.features)'
MF_FIT   = 'Fitment (product.metafields.custom.fitment)'
MF_MODEL = 'Model (product.metafields.custom.model)'
MF_PCAT  = 'Product category (product.metafields.custom.product_category)'
MF_INFO  = 'Product Information (product.metafields.custom.product_information)'
MF_SPEC  = 'Specifications (product.metafields.custom.specifications)'
MF_WHY   = 'Why choose this (product.metafields.custom.why_choose_this)'

# Model metafield -> make. "Gear" and "Parts" are catalogue buckets, not
# motorcycles, so products under them get no fitment records at all.
MAKE = {
    'sportster': 'Harley-Davidson', 'softail': 'Harley-Davidson',
    'dyna': 'Harley-Davidson', 'touring': 'Harley-Davidson',
    'triumph': 'Triumph', 'honda': 'Honda', 'indian': 'Indian',
}
NOT_A_MODEL = {'gear', 'parts', ''}

# The fitment grid mixes genuine model names with build styles ("Bobber
# Builds"), compatibility statements ("Not compatible with narrow-glide
# forks") and category blurbs. Only real model names belong in a fitment
# dropdown, so everything else is rejected.
DESCRIPTIVE = re.compile(
    r'^(all\b|any\b|most\b|universal|sitewide|parts\s*&|garage|apparel|fits\b|'
    r'not\b|stock\b|factory\b|direct\b|engine\s+types\b|installation\b|'
    r'brake\s+line\b|compatible\b|includes?\b)'
    r'|\b(builds?|conversions?|customs?|vintage|cruisers?|bobbers?|choppers?|'
    r'racers?|motorcycles?|wheels?|tyres?|tires?|handlebars?|controls?|'
    r'configurations?|systems?|setups?|required|hoops?|plates?|engines?|'
    r'carbureted|carburetted|forks?|variants?|models?|products?|accessories)\b'
    r'|\b(ignition|timing|cover|pattern|cables?|throttle|trims?|oem|converted|'
    r'clutch|bolt|lens|breather|belt|chain|mount)\b'
    r'|["”″]|\bmm\b', re.I)

MAKE_PREFIX = re.compile(r'^(harley[\s-]*davidson|harley|triumph|honda|indian)\s+', re.I)


def clean_model(raw):
    """Normalise one fitment-grid cell into zero or more model names."""
    out = []
    # "Iron 883, Forty-Eight, 1200 Custom" is three models in one cell
    for part in re.split(r',|/(?=\s)|\band\b(?!\s*\d)', raw):
        t = part.strip()
        t = re.sub(r'\([^)]*\)', '', t).strip()      # drop "(1995–2018+)"
        t = t.replace('(', ' ').replace(')', ' ')    # stray paren from comma-split
        t = re.sub(r'\s+', ' ', t).strip()
        t = MAKE_PREFIX.sub('', t).strip()           # drop redundant make prefix
        t = t.strip(' .;:-–—')
        if not t or len(t) > 26 or DESCRIPTIVE.search(t):
            continue
        if not re.search(r'[A-Za-z]', t):
            continue
        out.append(t.replace('|', '/'))
    return out


def strip_tags(s):
    s = re.sub(r'<style.*?</style>', ' ', s or '', flags=re.S | re.I)
    s = re.sub(r'<[^>]+>', ' ', s)
    return html.unescape(re.sub(r'\s+', ' ', s)).strip()


def parse_spec_rows(spec_html):
    """.spec-label / .spec-value pairs -> ["Label|Value", ...]"""
    if not spec_html:
        return []
    pairs = re.findall(
        r'spec-label"[^>]*>(.*?)</div>\s*<div class="spec-value"[^>]*>(.*?)</div>',
        spec_html, re.S | re.I)
    out = []
    for label, value in pairs:
        l, v = strip_tags(label), strip_tags(value)
        # the pipe is the field separator, so it can never appear in a cell
        l, v = l.replace('|', '/'), v.replace('|', '/')
        if l and v:
            out.append(f'{l}|{v}')
    return out[:20]


def parse_years(*texts):
    """Return (from, to) as strings, or None when no year is stated."""
    blob = ' '.join(t for t in texts if t)
    m = re.search(r'\b(19\d{2}|20\d{2})\s*[-–—]\s*(19\d{2}|20\d{2})\b', blob)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a <= b:
            return str(a), str(b)
    m = re.search(r'\b(19\d{2}|20\d{2})\s*\+', blob)
    if m:
        return m.group(1), str(CURRENT_YEAR)
    m = re.search(r'\b(19\d{2}|20\d{2})\b', blob)
    if m:
        return m.group(1), str(CURRENT_YEAR)
    return None


def parse_fitment_data(row):
    """Build "Make|Model|Years" records from the fitment HTML + Model field."""
    model_field = (row.get(MF_MODEL) or '').strip()
    key = model_field.lower()
    if key in NOT_A_MODEL:
        return []
    make = MAKE.get(key)
    if not make:
        # Model holds something unmapped — treat it as its own make/model pair
        make, model_field = model_field, model_field

    fit_html = row.get(MF_FIT) or ''
    grid = re.search(r'class="fitment-grid"[^>]*>(.*?)</div>\s*</div>',
                     fit_html, re.S | re.I)
    if not grid:
        grid = re.search(r'class="fitment-grid"[^>]*>(.*)', fit_html, re.S | re.I)
    submodels = []
    if grid:
        for cell in re.findall(r'<div[^>]*>(.*?)</div>', grid.group(1), re.S):
            submodels.extend(clean_model(strip_tags(cell)))

    years = parse_years(row.get('Title', ''), strip_tags(fit_html))
    span = f'{years[0]}-{years[1]}' if years else 'All years'

    records, seen = [], set()
    for name in [model_field] + submodels:      # family first, then submodels
        if not name:
            continue
        rec = f'{make}|{name}|{span}'
        if rec not in seen:
            seen.add(rec)
            records.append(rec)
    return records[:14]


# --------------------------------------------------------------------- API
def ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for p in ('/etc/ssl/cert.pem', '/opt/homebrew/etc/openssl@3/cert.pem'):
        if os.path.exists(p):
            return ssl.create_default_context(cafile=p)
    return ssl.create_default_context()


MUT_SET = """
mutation ImportProduct($input: ProductSetInput!) {
  productSet(synchronous: true, input: $input) {
    product { id handle }
    userErrors { field message code }
  }
}
"""
QUERY_SHOP = "query { shop { name myshopifyDomain currencyCode } }"
QUERY_HANDLES = """
query Handles($cursor: String) {
  products(first: 250, after: $cursor) {
    nodes { handle }
    pageInfo { hasNextPage endCursor }
  }
}
"""
QUERY_PUBS = "query { publications(first: 20) { nodes { id name } } }"
QUERY_LOC = "query { locations(first: 5) { nodes { id name isActive } } }"
MUT_PUBLISH = """
mutation Publish($id: ID!, $input: [PublicationInput!]!) {
  publishablePublish(id: $id, input: $input) { userErrors { field message } }
}
"""


class Shop:
    def __init__(self, domain, token, version):
        d = domain.strip().rstrip('/')
        for p in ('https://', 'http://'):
            if d.startswith(p):
                d = d[len(p):]
        self.url = f"https://{d.split('/')[0]}/admin/api/{version}/graphql.json"
        self.token = token
        self.ctx = ssl_context()

    def call(self, query, variables=None, retries=5):
        body = json.dumps({"query": query, "variables": variables or {}}).encode()
        for attempt in range(retries):
            req = urllib.request.Request(self.url, data=body, method='POST', headers={
                'Content-Type': 'application/json',
                'X-Shopify-Access-Token': self.token})
            try:
                with urllib.request.urlopen(req, timeout=90, context=self.ctx) as r:
                    payload = json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise SystemExit(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
            except (urllib.error.URLError, ConnectionError, TimeoutError,
                    http.client.HTTPException, OSError) as e:
                # Shopify drops long-lived connections mid-import; a reset here
                # is transient and the request is safe to repeat because
                # productSet is keyed on handle.
                if attempt < retries - 1:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise SystemExit(f"connection failed after {retries} attempts: {e!r}")
            errs = payload.get('errors')
            if errs:
                if any('THROTTLED' in json.dumps(e) for e in errs) and attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise SystemExit("GraphQL errors: " + json.dumps(errs)[:400])
            return payload['data']
        raise SystemExit("exhausted retries")


# ------------------------------------------------------------------ build
def group_rows(path):
    with open(path, encoding='utf-8-sig', newline='') as fh:
        rows = list(csv.DictReader(fh))
    by = OrderedDict()
    for r in rows:
        h = (r.get('Handle') or '').strip()
        if h:
            by.setdefault(h, []).append(r)
    return by


def build_input(handle, rows, location_id, stock_default):
    head = rows[0]
    opt_names = []
    for i in (1, 2, 3):
        n = (head.get(f'Option{i} Name') or '').strip()
        if n and n.lower() != 'title':
            opt_names.append((i, n))

    variant_rows = [r for r in rows
                    if (r.get('Variant SKU') or '').strip()
                    or (r.get('Variant Price') or '').strip()]
    if not variant_rows:
        variant_rows = [head]

    # images, in CSV order, de-duplicated
    files, seen_img = [], set()
    for r in rows:
        src = (r.get('Image Src') or '').strip()
        if src and src not in seen_img:
            seen_img.add(src)
            files.append({"originalSource": src, "contentType": "IMAGE",
                          "alt": (r.get('Image Alt Text') or '').strip()[:512] or None})
    for f in files:
        if f["alt"] is None:
            del f["alt"]

    if opt_names:
        values = {n: [] for _, n in opt_names}
        for r in variant_rows:
            for i, n in opt_names:
                v = (r.get(f'Option{i} Value') or '').strip()
                if v and v not in values[n]:
                    values[n].append(v)
        product_options = [{"name": n, "values": [{"name": v} for v in values[n]]}
                           for _, n in opt_names if values[n]]
    else:
        product_options = [{"name": "Title", "values": [{"name": "Default Title"}]}]

    variants = []
    for idx, r in enumerate(variant_rows, start=1):
        if opt_names:
            ovs = []
            for i, n in opt_names:
                v = (r.get(f'Option{i} Value') or '').strip()
                if v:
                    ovs.append({"optionName": n, "name": v})
            if not ovs:
                continue
        else:
            ovs = [{"optionName": "Title", "name": "Default Title"}]

        price = (r.get('Variant Price') or '').strip() or '0.00'
        v = {"optionValues": ovs, "price": price, "position": idx}
        cap = (r.get('Variant Compare At Price') or '').strip()
        if cap:
            v["compareAtPrice"] = cap
        bc = (r.get('Variant Barcode') or '').strip()
        if bc:
            v["barcode"] = bc

        inv_item = {}
        sku = (r.get('Variant SKU') or '').strip()
        if sku:
            inv_item["sku"] = sku
        grams = (r.get('Variant Grams') or '').strip()
        if grams:
            try:
                inv_item["measurement"] = {"weight": {
                    "value": float(grams) / 1000.0, "unit": "KILOGRAMS"}}
            except ValueError:
                pass
        tracker = (r.get('Variant Inventory Tracker') or '').strip().lower()
        tracked = tracker == 'shopify'
        inv_item["tracked"] = tracked
        req_ship = (r.get('Variant Requires Shipping') or 'TRUE').strip().upper() != 'FALSE'
        inv_item["requiresShipping"] = req_ship
        if inv_item:
            v["inventoryItem"] = inv_item

        pol = (r.get('Variant Inventory Policy') or '').strip().upper()
        v["inventoryPolicy"] = 'CONTINUE' if pol == 'CONTINUE' else 'DENY'
        v["taxable"] = (r.get('Variant Taxable') or 'TRUE').strip().upper() != 'FALSE'

        if tracked and location_id:
            qty = (r.get('Variant Inventory Qty') or '').strip()
            try:
                qty = int(float(qty))
            except (TypeError, ValueError):
                qty = stock_default
            if qty <= 0:
                qty = stock_default
            v["inventoryQuantities"] = [{"locationId": location_id,
                                         "name": "available", "quantity": qty}]
        variants.append(v)

    metafields = []
    for key, col, mtype in (
        ('faqs', MF_FAQS, 'multi_line_text_field'),
        ('features', MF_FEAT, 'multi_line_text_field'),
        ('fitment', MF_FIT, 'multi_line_text_field'),
        ('model', MF_MODEL, 'single_line_text_field'),
        ('product_category', MF_PCAT, 'single_line_text_field'),
        ('product_information', MF_INFO, 'multi_line_text_field'),
        ('specifications', MF_SPEC, 'multi_line_text_field'),
        ('why_choose_this', MF_WHY, 'multi_line_text_field'),
    ):
        val = (head.get(col) or '').strip()
        if val:
            metafields.append({"namespace": "custom", "key": key,
                               "type": mtype, "value": val})

    # the theme reads custom.category for the breadcrumb
    pcat = (head.get(MF_PCAT) or '').strip()
    if pcat:
        metafields.append({"namespace": "custom", "key": "category",
                           "type": "single_line_text_field", "value": pcat})

    # --- the two derived metafields ---
    specs = parse_spec_rows(head.get(MF_SPEC) or '')
    if specs:
        metafields.append({"namespace": "custom", "key": "spec_rows",
                           "type": "list.single_line_text_field",
                           "value": json.dumps(specs)})
    fit = parse_fitment_data(head)
    if fit:
        metafields.append({"namespace": "custom", "key": "fitment_data",
                           "type": "list.single_line_text_field",
                           "value": json.dumps(fit)})

    status = (head.get('Status') or 'active').strip().upper()
    if status not in ('ACTIVE', 'DRAFT', 'ARCHIVED'):
        status = 'ACTIVE'

    inp = {
        "handle": handle,
        "title": (head.get('Title') or handle).strip(),
        "descriptionHtml": head.get('Body (HTML)') or '',
        "vendor": (head.get('Vendor') or '').strip() or 'Kinetic Motorcycles',
        "productType": (head.get('Type') or '').strip(),
        "status": status,
        "productOptions": product_options,
        "variants": variants,
        "metafields": metafields,
    }
    tags = [t.strip() for t in (head.get('Tags') or '').split(',') if t.strip()]
    if tags:
        inp["tags"] = tags[:250]
    seo_t = (head.get('SEO Title') or '').strip()
    seo_d = (head.get('SEO Description') or '').strip()
    if seo_t or seo_d:
        inp["seo"] = {k: v for k, v in (("title", seo_t), ("description", seo_d)) if v}
    if files:
        inp["files"] = files[:20]
    return inp, len(specs), len(fit)


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
    ap.add_argument('--csv', default=os.path.join(ROOT, 'products_export_1 1.csv'))
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--publish', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--stock', type=int, default=25)
    ap.add_argument('--skip-existing', action='store_true',
                    help='skip handles already in the store. Use when resuming '
                         'an interrupted run: productSet would otherwise re-send '
                         'the image set for products that already have it.')
    ap.add_argument('--env', default=os.path.join(ROOT, '.env'))
    args = ap.parse_args()

    env = load_env(args.env)
    domain = env.get('SHOPIFY_STORE_DOMAIN')
    token = env.get('SHOPIFY_ADMIN_TOKEN')
    if not domain or not token:
        raise SystemExit('missing SHOPIFY_STORE_DOMAIN / SHOPIFY_ADMIN_TOKEN in .env')
    if token.startswith('shpss_'):
        raise SystemExit("token is an API secret key (shpss_); need an Admin API "
                         "access token (shpat_)")

    shop = Shop(domain, token, env.get('SHOPIFY_API_VERSION') or '2025-07')
    info = shop.call(QUERY_SHOP)['shop']
    groups = group_rows(args.csv)
    if args.limit:
        groups = OrderedDict(list(groups.items())[:args.limit])

    print(f"store : {info['name']} ({info['myshopifyDomain']}, {info['currencyCode']})")
    print(f"csv   : {os.path.basename(args.csv)}  products={len(groups)}")
    print(f"mode  : {'APPLY' if args.apply else 'DRY RUN'}\n")

    location_id = None
    if args.apply:
        act = [l for l in shop.call(QUERY_LOC)['locations']['nodes'] if l['isActive']]
        location_id = act[0]['id'] if act else None
    pub_id = None
    if args.apply and args.publish:
        for n in shop.call(QUERY_PUBS)['publications']['nodes']:
            if (n.get('name') or '').lower() == 'online store':
                pub_id = n['id']

    existing = set()
    if args.skip_existing:
        cursor = None
        while True:
            page = shop.call(QUERY_HANDLES, {"cursor": cursor})['products']
            existing.update(n['handle'] for n in page['nodes'])
            if not page['pageInfo']['hasNextPage']:
                break
            cursor = page['pageInfo']['endCursor']
        already = sum(1 for h in groups if h in existing)
        print(f"already in store: {already}/{len(groups)} — skipping those\n")

    ok = fail = skipped = 0
    no_fit = no_spec = 0
    failures = []
    for i, (handle, rows) in enumerate(groups.items(), 1):
        if handle in existing:
            skipped += 1
            continue
        inp, nspec, nfit = build_input(handle, rows, location_id, args.stock)
        if not nfit:
            no_fit += 1
        if not nspec:
            no_spec += 1

        if not args.apply:
            if i <= 10 or i % 40 == 0:
                print(f"  [{i:3d}/{len(groups)}] {handle[:52]:54s} "
                      f"v={len(inp['variants']):2d} img={len(inp.get('files',[])):2d} "
                      f"spec={nspec:2d} fit={nfit:2d}")
            ok += 1
            continue

        res = shop.call(MUT_SET, {"input": inp})['productSet']
        if res['userErrors']:
            fail += 1
            failures.append((handle, res['userErrors'][:2]))
            print(f"  [{i:3d}/{len(groups)}] FAIL {handle[:48]}: {res['userErrors'][:1]}")
            continue
        if pub_id:
            shop.call(MUT_PUBLISH, {"id": res['product']['id'],
                                    "input": [{"publicationId": pub_id}]})
        ok += 1
        if i % 10 == 0 or i == len(groups):
            print(f"  [{i:3d}/{len(groups)}] ok={ok} fail={fail}   last={handle[:44]}")

    print(f"\n{'imported' if args.apply else 'would import'}: {ok}   "
          f"failed: {fail}   skipped (already present): {skipped}")
    print(f"products with no derived fitment_data: {no_fit}  (Gear/Parts have no model)")
    print(f"products with no derived spec_rows   : {no_spec}")
    if failures:
        print("\nfailures:")
        for h, e in failures[:15]:
            print(f"  {h}: {e}")


if __name__ == '__main__':
    main()
