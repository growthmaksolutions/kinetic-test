#!/usr/bin/env python3
"""
Seed Kinetic Motorcycles catalogue products into a Shopify store.

Every product carries the metafields the redesigned product page consumes:

  custom.fitment_data  list.single_line_text_field  "Make|Model|2006-2017"
                       -> drives the Product Fitment checker
  custom.spec_rows     list.single_line_text_field  "Label|Value"
                       -> drives the Product Specs table
  custom.model         single_line_text_field       -> breadcrumb + fallback fitment
  custom.category, custom.features, custom.fitment, custom.why_choose_this
                       -> the product accordion

Credentials come from .env (git-ignored). Never pass a token on the command
line: it lands in your shell history and in the process list.

Safe by default — prints a plan and writes nothing unless you pass --apply.

  python3 scripts/seed_products.py                    # dry run
  python3 scripts/seed_products.py --apply            # create as DRAFT
  python3 scripts/seed_products.py --apply --status active --publish

Re-running is safe: a product whose handle already exists is skipped, so the
script never creates duplicates.
"""
import argparse, json, os, ssl, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ssl_context():
    """Homebrew Python ships without a CA bundle, so urllib fails TLS with
    CERTIFICATE_VERIFY_FAILED. Fall back to certifi, then to the macOS system
    bundle. Verification stays on in every case."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for path in ('/etc/ssl/cert.pem', '/usr/local/etc/openssl/cert.pem',
                 '/opt/homebrew/etc/openssl@3/cert.pem'):
        if os.path.exists(path):
            return ssl.create_default_context(cafile=path)
    return ssl.create_default_context()


# --------------------------------------------------------------- credentials
def load_env(path):
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


# ------------------------------------------------------------------ products
# Fitment spans deliberately cover several makes so the checker can return a
# real "not compatible" verdict, not just confirmations.
PRODUCTS = [
    {
        "handle": "ignition-coil-relocator-sportster",
        "title": "Ignition Coil Relocator — Harley-Davidson Sportster",
        "type": "Electrical",
        "price": "89.00", "compare_at": "109.00", "sku": "KM-ICR-XL-01",
        "weight": 0.45,
        "tags": ["sportster", "harley-davidson", "electrical", "relocator",
                 "fits:Harley-Davidson:Sportster:2004-2022"],
        "model": "Sportster", "category": "Electrical",
        "description": "<p>Moves the ignition coil out from under the tank and into clean air, "
                       "freeing space for a tank lift or a relocated key switch. Machined from "
                       "billet, hard anodised, and supplied with all stainless hardware.</p>",
        "fitment_data": ["Harley-Davidson|Sportster|2004-2022"],
        "spec_rows": ["Material|6061-T6 billet aluminium", "Finish|Hard anodised black",
                      "Hardware|Stainless, included", "Install time|45 minutes",
                      "Origin|Designed & machined in the USA"],
        "features": "Billet construction, no drilling required, factory wiring reaches without extension.",
        "fitment": "Fits Harley-Davidson Sportster models 2004 through 2022, carburetted and EFI.",
        "why": "Frees tank space without cutting or drilling the frame.",
    },
    {
        "handle": "tank-lift-kit-sportster",
        "title": "Tank Lift Kit with Coil & Key Relocation — Sportster",
        "type": "Chassis",
        "price": "129.00", "compare_at": "", "sku": "KM-TLK-XL-02",
        "weight": 0.80,
        "tags": ["sportster", "harley-davidson", "chassis", "tank-lift",
                 "fits:Harley-Davidson:Sportster:1995-2022"],
        "model": "Sportster", "category": "Suspension and Chassis",
        "description": "<p>Lifts the fuel tank to expose the top of the motor and relocates both "
                       "the coil and the key switch in one kit. Bolt-on, fully reversible, and "
                       "supplied with every bracket and fastener needed.</p>",
        "fitment_data": ["Harley-Davidson|Sportster|1995-2022"],
        "spec_rows": ["Material|6061-T6 billet aluminium", "Lift height|38 mm",
                      "Finish|Hard anodised black", "Hardware|Stainless, included",
                      "Install time|90 minutes", "Origin|Designed & machined in the USA"],
        "features": "Complete bolt-on kit, reversible, includes coil and key relocation brackets.",
        "fitment": "Fits Harley-Davidson Sportster 1995 through 2022.",
        "why": "One kit replaces three separate purchases and a lot of fabrication.",
    },
    {
        "handle": "heavy-knurl-shifter-peg",
        "title": "Heavy Knurl Shifter Peg",
        "type": "Controls",
        "price": "49.00", "compare_at": "", "sku": "KM-SPG-HK-03",
        "weight": 0.22,
        "tags": ["sportster", "dyna", "harley-davidson", "controls", "pegs",
                 "fits:Harley-Davidson:Sportster:2004-2022",
                 "fits:Harley-Davidson:Dyna:2006-2017"],
        "model": "Sportster", "category": "Controls",
        "description": "<p>Aggressive knurl that holds a boot in the wet. Turned from solid bar, "
                       "threaded to the factory shifter, and finished to survive road salt.</p>",
        "fitment_data": ["Harley-Davidson|Sportster|2004-2022",
                         "Harley-Davidson|Dyna|2006-2017"],
        "spec_rows": ["Material|303 stainless steel", "Finish|Bead blasted",
                      "Thread|3/8\"-16 UNC", "Weight|220 g",
                      "Origin|Designed & machined in the USA"],
        "features": "Deep knurl for wet-weather grip, solid stainless, direct thread-on fit.",
        "fitment": "Fits Harley-Davidson Sportster 2004-2022 and Dyna 2006-2017.",
        "why": "Grip that does not polish smooth after a season.",
    },
    {
        "handle": "composite-wide-grips",
        "title": "Composite Wide Grips — 1\" Bars",
        "type": "Controls",
        "price": "79.00", "compare_at": "95.00", "sku": "KM-GRP-CW-04",
        "weight": 0.31,
        "tags": ["sportster", "dyna", "softail", "harley-davidson", "controls", "grips",
                 "fits:Harley-Davidson:Sportster:2004-2022",
                 "fits:Harley-Davidson:Dyna:2006-2017",
                 "fits:Harley-Davidson:Softail:2000-2023"],
        "model": "Sportster", "category": "Controls",
        "description": "<p>A wider body spreads load across the palm and takes the sting out of a "
                       "long day. Composite core with a machined billet end cap.</p>",
        "fitment_data": ["Harley-Davidson|Sportster|2004-2022",
                         "Harley-Davidson|Dyna|2006-2017",
                         "Harley-Davidson|Softail|2000-2023"],
        "spec_rows": ["Bar diameter|1 inch", "Material|Composite over billet core",
                      "Finish|Anodised end caps", "Throttle|Cable and fly-by-wire",
                      "Origin|Designed & machined in the USA"],
        "features": "Wide profile, vibration damping core, fits cable and fly-by-wire throttles.",
        "fitment": "Fits 1 inch bars on Harley-Davidson Sportster, Dyna and Softail.",
        "why": "Less hand fatigue without the bulk of a foam grip.",
    },
    {
        "handle": "milwaukee-8-throttle-body-gasket",
        "title": "Milwaukee-8 Throttle Body Gasket",
        "type": "Intake",
        "price": "34.00", "compare_at": "", "sku": "KM-TBG-M8-05",
        "weight": 0.06,
        "tags": ["milwaukee-8", "touring", "harley-davidson", "intake", "gasket",
                 "fits:Harley-Davidson:Milwaukee-8:2017-2024",
                 "fits:Harley-Davidson:Touring:2017-2024"],
        "model": "Milwaukee-8", "category": "Intake",
        "description": "<p>Precision-cut sealing gasket for the Milwaukee-8 throttle body. Holds "
                       "its seal through heat cycling where the paper original hardens and leaks.</p>",
        "fitment_data": ["Harley-Davidson|Milwaukee-8|2017-2024",
                         "Harley-Davidson|Touring|2017-2024"],
        "spec_rows": ["Material|Silicone-faced composite", "Thickness|1.6 mm",
                      "Temperature range|-40 to 230 C", "Sold as|Single gasket",
                      "Origin|Designed & made in the USA"],
        "features": "Survives heat cycling, reusable, exact factory dimensions.",
        "fitment": "Fits Harley-Davidson Milwaukee-8 engines and Touring models 2017-2024.",
        "why": "The factory paper gasket is a known leak point after a few seasons.",
    },
    {
        "handle": "bar-end-mirror-set",
        "title": "Bar-End Mirror Set — Triumph & Honda",
        "type": "Controls",
        "price": "149.00", "compare_at": "179.00", "sku": "KM-MIR-BE-06",
        "weight": 0.54,
        "tags": ["triumph", "honda", "controls", "mirrors",
                 "fits:Triumph:Bonneville:2016-2024",
                 "fits:Triumph:Street Twin:2016-2024",
                 "fits:Honda:Rebel:2017-2024"],
        "model": "Bonneville", "category": "Controls",
        "description": "<p>Machined bar-end mirrors with a convex glass that actually shows the "
                       "lane behind you. Clamps inside the bar, adjusts through a full arc, and "
                       "holds position over rough surfaces.</p>",
        "fitment_data": ["Triumph|Bonneville|2016-2024",
                         "Triumph|Street Twin|2016-2024",
                         "Honda|Rebel|2017-2024"],
        "spec_rows": ["Material|Billet aluminium", "Glass|Convex, anti-glare",
                      "Bar fitment|Internal clamp, 14-18 mm bore", "Sold as|Pair",
                      "Origin|Designed & machined in the USA"],
        "features": "Sold as a pair, convex anti-glare glass, internal bar clamp.",
        "fitment": "Fits Triumph Bonneville and Street Twin 2016-2024, Honda Rebel 2017-2024.",
        "why": "A genuinely usable field of view, not a styling accessory.",
    },
]

MUT_CREATE = """
mutation CreateKineticProduct($product: ProductCreateInput!) {
  productCreate(product: $product) {
    product { id handle title variants(first: 1) { nodes { id } } }
    userErrors { field message }
  }
}
"""

MUT_VARIANT = """
mutation SetVariant($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants { id sku price }
    userErrors { field message }
  }
}
"""

QUERY_LOOKUP = """
query FindByHandle($q: String!) {
  products(first: 1, query: $q) { nodes { id handle } }
}
"""

QUERY_SHOP = "query { shop { name myshopifyDomain currencyCode } }"

QUERY_PUBS = "query { publications(first: 20) { nodes { id catalog { title } } } }"

MUT_PUBLISH = """
mutation Publish($id: ID!, $input: [PublicationInput!]!) {
  publishablePublish(id: $id, input: $input) {
    userErrors { field message }
  }
}
"""


def normalize_domain(d):
    """Accept https://shop.myshopify.com/ as readily as shop.myshopify.com."""
    d = d.strip().rstrip('/')
    for prefix in ('https://', 'http://'):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d.split('/')[0]


class Shop:
    def __init__(self, domain, token, version):
        self.domain = normalize_domain(domain)
        self.url = f"https://{self.domain}/admin/api/{version}/graphql.json"
        self.token = token
        self.ctx = ssl_context()

    def call(self, query, variables=None):
        body = json.dumps({"query": query, "variables": variables or {}}).encode()
        req = urllib.request.Request(self.url, data=body, method='POST', headers={
            'Content-Type': 'application/json',
            'X-Shopify-Access-Token': self.token,
        })
        try:
            with urllib.request.urlopen(req, timeout=45, context=self.ctx) as r:
                payload = json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors='replace')[:300]
            if e.code == 401:
                raise SystemExit(
                    f"HTTP 401 from Shopify: {detail}\n"
                    "The token was rejected. Confirm it is the Admin API access token\n"
                    "(starts with 'shpat_'), that the app is installed on this store, and\n"
                    "that read_products + write_products scopes are granted.")
            raise SystemExit(f"HTTP {e.code} from Shopify: {detail}")
        except urllib.error.URLError as e:
            raise SystemExit(f"Could not reach {self.url}: {e.reason}")
        if payload.get('errors'):
            raise SystemExit("GraphQL errors: " + json.dumps(payload['errors'])[:400])
        return payload['data']


def metafields_for(p):
    mf = [
        {"namespace": "custom", "key": "fitment_data", "type": "list.single_line_text_field",
         "value": json.dumps(p["fitment_data"])},
        {"namespace": "custom", "key": "spec_rows", "type": "list.single_line_text_field",
         "value": json.dumps(p["spec_rows"])},
        {"namespace": "custom", "key": "model", "type": "single_line_text_field",
         "value": p["model"]},
        {"namespace": "custom", "key": "category", "type": "single_line_text_field",
         "value": p["category"]},
    ]
    for key, val in (("features", p["features"]), ("fitment", p["fitment"]),
                     ("why_choose_this", p["why"])):
        mf.append({"namespace": "custom", "key": key,
                   "type": "multi_line_text_field", "value": val})
    return mf


def main():
    ap = argparse.ArgumentParser(description="Seed Kinetic products into Shopify.")
    ap.add_argument('--apply', action='store_true', help='actually write (default: dry run)')
    ap.add_argument('--status', choices=['draft', 'active'], default='draft')
    ap.add_argument('--publish', action='store_true',
                    help='publish to the Online Store channel (needs --status active to be visible)')
    ap.add_argument('--env', default=os.path.join(ROOT, '.env'))
    args = ap.parse_args()

    env = load_env(args.env)
    domain = env.get('SHOPIFY_STORE_DOMAIN') or os.environ.get('SHOPIFY_STORE_DOMAIN')
    token = env.get('SHOPIFY_ADMIN_TOKEN') or os.environ.get('SHOPIFY_ADMIN_TOKEN')
    version = env.get('SHOPIFY_API_VERSION') or '2025-07'

    if not domain or not token:
        raise SystemExit(f"Missing SHOPIFY_STORE_DOMAIN / SHOPIFY_ADMIN_TOKEN in {args.env}\n"
                         f"Copy .env.example to .env and fill it in.")
    if 'FAKE' in token or token.endswith('xxxx'):
        raise SystemExit("SHOPIFY_ADMIN_TOKEN is still a placeholder — put the real token in .env")

    # shpss_ is an app's SHARED SECRET (used to verify webhook HMACs), not a
    # bearer credential — the Admin API will reject it with 401.
    if token.startswith('shpss_'):
        raise SystemExit(
            "SHOPIFY_ADMIN_TOKEN starts with 'shpss_', which is the app's API secret key,\n"
            "not an Admin API access token. The Admin API needs a token starting with 'shpat_'.\n\n"
            "In Shopify admin: Settings -> Apps and sales channels -> Develop apps -> your app\n"
            "  -> API credentials tab -> Admin API access token -> Install app / Reveal token once.\n"
            "It is shown only once, and is a different value from the API key and secret key.")

    shop = Shop(domain, token, version)
    info = shop.call(QUERY_SHOP)['shop']
    print(f"store    : {info['name']}  ({info['myshopifyDomain']}, {info['currencyCode']})")
    print(f"api      : {version}")
    print(f"mode     : {'APPLY' if args.apply else 'DRY RUN (nothing will be written)'}")
    print(f"status   : {args.status.upper()}\n")

    pub_id = None
    if args.publish and args.apply:
        for node in shop.call(QUERY_PUBS)['publications']['nodes']:
            title = (node.get('catalog') or {}).get('title') or ''
            if 'online store' in title.lower():
                pub_id = node['id']
        print(f"publication: {pub_id or 'Online Store not found — skipping publish'}\n")

    created = skipped = 0
    for p in PRODUCTS:
        existing = shop.call(QUERY_LOOKUP, {"q": f"handle:{p['handle']}"})['products']['nodes']
        if existing:
            print(f"  skip   {p['handle']}  (already exists)")
            skipped += 1
            continue

        if not args.apply:
            print(f"  would create  {p['handle']:42s} {p['sku']:14s} {p['price']:>8s}  "
                  f"fitment={len(p['fitment_data'])} specs={len(p['spec_rows'])}")
            created += 1
            continue

        data = shop.call(MUT_CREATE, {"product": {
            "title": p["title"], "handle": p["handle"],
            "descriptionHtml": p["description"],
            "vendor": "Kinetic Motorcycles", "productType": p["type"],
            "tags": p["tags"], "status": args.status.upper(),
            "metafields": metafields_for(p),
        }})['productCreate']

        if data['userErrors']:
            print(f"  FAIL   {p['handle']}: {data['userErrors']}")
            continue

        prod = data['product']
        variant_id = prod['variants']['nodes'][0]['id']

        variant = {
            "id": variant_id, "price": p["price"],
            "inventoryItem": {
                "sku": p["sku"], "tracked": True,
                "measurement": {"weight": {"value": p["weight"], "unit": "KILOGRAMS"}},
            },
        }
        if p["compare_at"]:
            variant["compareAtPrice"] = p["compare_at"]

        verr = shop.call(MUT_VARIANT, {"productId": prod['id'],
                                       "variants": [variant]})['productVariantsBulkUpdate']['userErrors']
        if verr:
            print(f"  warn   {p['handle']}: variant update -> {verr}")

        if pub_id:
            perr = shop.call(MUT_PUBLISH, {"id": prod['id'],
                                           "input": [{"publicationId": pub_id}]})['publishablePublish']['userErrors']
            if perr:
                print(f"  warn   {p['handle']}: publish -> {perr}")

        print(f"  created {p['handle']:42s} {p['sku']:14s} {p['price']:>8s}")
        created += 1

    verb = 'created' if args.apply else 'to create'
    print(f"\n{verb}: {created}   skipped (already present): {skipped}")
    if not args.apply:
        print("Re-run with --apply to write these to the store.")


if __name__ == '__main__':
    main()
