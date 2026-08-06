#!/usr/bin/env python3
"""
Generate a Shopify-importable product CSV from the same catalogue the API
seeder uses, so products can be added with no API token at all:

    Shopify admin -> Products -> Import -> upload the CSV

Why this still lights up the redesigned product page:

  Fitment checker  reads custom.fitment_data first, but falls back to
                   "fits:Make:Model:Years" TAGS — and tags are a plain CSV
                   column that always imports cleanly. So the checker works
                   even if the metafield columns are ignored.
  Specs table      auto-rows come from SKU / vendor / type / weight, all
                   standard CSV columns, plus the editor rows already saved
                   in templates/product.json.

Metafield columns are included too. Shopify's support for metafields on
import varies by store, so treat them as a bonus: verify one product after
importing, and if the metafields did not land, the tag fallback already has
the fitment checker covered.
"""
import csv, importlib.util, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    'seed', os.path.join(ROOT, 'scripts', 'seed_products.py'))
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)

MF = [
    ('custom.fitment_data',    'list.single_line_text_field', lambda p: json.dumps(p['fitment_data'])),
    ('custom.spec_rows',       'list.single_line_text_field', lambda p: json.dumps(p['spec_rows'])),
    ('custom.model',           'single_line_text_field',      lambda p: p['model']),
    ('custom.category',        'single_line_text_field',      lambda p: p['category']),
    ('custom.features',        'multi_line_text_field',       lambda p: p['features']),
    ('custom.fitment',         'multi_line_text_field',       lambda p: p['fitment']),
    ('custom.why_choose_this', 'multi_line_text_field',       lambda p: p['why']),
]

BASE = [
    'Handle', 'Title', 'Body (HTML)', 'Vendor', 'Type', 'Tags', 'Published',
    'Option1 Name', 'Option1 Value',
    'Variant SKU', 'Variant Grams', 'Variant Inventory Tracker',
    'Variant Inventory Qty', 'Variant Inventory Policy',
    'Variant Fulfillment Service', 'Variant Price', 'Variant Compare At Price',
    'Variant Requires Shipping', 'Variant Taxable',
    'Gift Card', 'SEO Title', 'SEO Description', 'Status',
]
HEADERS = BASE + [f'Metafield: {k} [{t}]' for k, t, _ in MF]

out = os.path.join(ROOT, 'scripts', 'kinetic-products.csv')
with open(out, 'w', newline='', encoding='utf-8') as fh:
    w = csv.writer(fh)
    w.writerow(HEADERS)
    for p in seed.PRODUCTS:
        row = [
            p['handle'], p['title'], p['description'], 'Kinetic Motorcycles',
            p['type'], ', '.join(p['tags']), 'TRUE',
            'Title', 'Default Title',
            p['sku'], int(round(p['weight'] * 1000)), 'shopify',
            25, 'deny', 'manual',
            p['price'], p['compare_at'] or '',
            'TRUE', 'TRUE',
            'FALSE', p['title'][:70],
            p['description'].replace('<p>', '').replace('</p>', '').strip()[:320],
            'active',
        ]
        row += [fn(p) for _, _, fn in MF]
        w.writerow(row)

print(f'wrote {out}')
print(f'  products: {len(seed.PRODUCTS)}   columns: {len(HEADERS)}')
print(f'  metafield columns: {len(MF)}')
