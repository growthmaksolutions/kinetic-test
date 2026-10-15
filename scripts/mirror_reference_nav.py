#!/usr/bin/env python3
"""
Mirror the reference store's header menu, and the collections it links to,
onto the dev store, so the COLLECTIONS mega menu matches the reference.

The reference store is only read. Writes go to the --to store, which must be
a development store: the script refuses to write to production.

Collections are smart collections on the custom.model and
custom.product_category metafield definitions. Both stores define those, so
each copied rule is re-pointed at the target's own definition and fills itself
with the target's matching products. Existing handles on the target are left
alone, which makes re-runs safe.

Menus copied: main-menu, plus the per-column menus the mega menu and footer
brand blocks look up (sportster, softail, ...). Footer, company and support
menus are not touched. The target's menus are snapshotted to backups/ before
any write.

  python3 scripts/mirror_reference_nav.py                 # dry run
  python3 scripts/mirror_reference_nav.py --apply
"""
import argparse, datetime, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backup_live import Shop, load_env, ROOT

ITEM = 'id title type url resourceId'
Q_MENUS = '{ menus(first:100){ nodes{ id handle title items{ %s items{ %s items{ %s } } } } } }' % (ITEM, ITEM, ITEM)
Q_COLLECTION = '''query($h:String!){ collectionByHandle(handle:$h){
  id handle title sortOrder descriptionHtml templateSuffix
  image{ url altText } seo{ title description }
  ruleSet{ appliedDisjunctively rules{ column relation condition
    conditionObject{ ... on CollectionRuleMetafieldCondition{ metafieldDefinition{ namespace key } } } } }
  description: metafield(namespace:"custom", key:"category_description"){ value }
  children: metafield(namespace:"custom", key:"category_collections"){
    references(first:50){ nodes{ ... on Collection{ handle } } } }
} }'''
Q_DEFS = '{ metafieldDefinitions(first:100, ownerType:PRODUCT){ nodes{ id namespace key } } }'
Q_PAGES = '{ pages(first:250){ nodes{ id handle title } } blogs(first:50){ nodes{ id handle title } } }'
Q_PUBS = '{ publications(first:20){ nodes{ id name } } }'
Q_HANDLES = 'query($c:String){ collections(first:250, after:$c){ nodes{ id handle } pageInfo{ hasNextPage endCursor } } }'

M_CREATE = '''mutation($input:CollectionInput!){ collectionCreate(input:$input){
  collection{ id handle } userErrors{ field message } } }'''
M_PUBLISH = '''mutation($id:ID!, $p:ID!){ publishablePublish(id:$id, input:[{publicationId:$p}]){
  userErrors{ field message } } }'''
M_METAFIELDS = '''mutation($m:[MetafieldsSetInput!]!){ metafieldsSet(metafields:$m){
  userErrors{ field message } } }'''
M_MENU = '''mutation($id:ID!, $title:String!, $handle:String!, $items:[MenuItemUpdateInput!]!){
  menuUpdate(id:$id, title:$title, handle:$handle, items:$items){ menu{ handle } userErrors{ field message } } }'''
M_MENU_NEW = '''mutation($title:String!, $handle:String!, $items:[MenuItemCreateInput!]!){
  menuCreate(title:$title, handle:$handle, items:$items){ menu{ handle } userErrors{ field message } } }'''


def must(shop, q, v=None):
    d = shop.call(q, v)
    if d is None:
        raise SystemExit(f'API call failed: {shop.denied[-1] if shop.denied else "unknown"}')
    for payload in d.values():
        errs = isinstance(payload, dict) and payload.get('userErrors')
        if errs:
            raise SystemExit(f'userErrors: {json.dumps(errs)}')
    return d


def collection_handles(shop):
    out, cur = {}, None
    while True:
        p = must(shop, Q_HANDLES, {'c': cur})['collections']
        out.update({n['handle']: n['id'] for n in p['nodes']})
        if not p['pageInfo']['hasNextPage']:
            return out
        cur = p['pageInfo']['endCursor']


def handle_of(url):
    return url.rstrip('/').split('/')[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='src', default=os.path.join(ROOT, '.env.live'))
    ap.add_argument('--to', dest='dst', default=os.path.join(ROOT, '.env'))
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    src, dst = Shop(load_env(args.src)), Shop(load_env(args.dst))
    target = must(dst, '{ shop{ myshopifyDomain plan{ partnerDevelopment } } }')['shop']
    if not target['plan']['partnerDevelopment']:
        raise SystemExit(f"refusing to write: {target['myshopifyDomain']} is not a development store")
    print(f"mode: {'APPLY' if args.apply else 'DRY RUN'}  target: {target['myshopifyDomain']}")

    ref_menus = {m['handle']: m for m in must(src, Q_MENUS)['menus']['nodes']}
    main_menu = ref_menus['main-menu']
    # The mega menu looks each column up as linklists[column.title | handleize].
    copy_menus = ['main-menu'] + [c['title'].strip().lower().replace(' ', '-')
                                  for top in main_menu['items'] for c in top['items'] or []]
    copy_menus = [h for h in dict.fromkeys(copy_menus) if h in ref_menus]

    # Every collection a copied menu links to, plus any they list as children.
    wanted, queue = {}, [handle_of(i['url']) for h in copy_menus for i in _walk(ref_menus[h]['items'])
                         if i['type'] == 'COLLECTION']
    while queue:
        h = queue.pop(0)
        if h in wanted:
            continue
        c = must(src, Q_COLLECTION, {'h': h})['collectionByHandle']
        if not c:
            raise SystemExit(f'reference menu links to missing collection {h}')
        wanted[h] = c
        queue += [n['handle'] for n in ((c['children'] or {}).get('references') or {}).get('nodes', [])]

    defs = {f"{d['namespace']}.{d['key']}": d['id'] for d in must(dst, Q_DEFS)['metafieldDefinitions']['nodes']}
    existing = collection_handles(dst)
    to_create = [c for h, c in wanted.items() if h not in existing]
    print(f'reference collections linked: {len(wanted)}  already on target: {len(wanted) - len(to_create)}  to create: {len(to_create)}')

    for c in to_create:
        rules = []
        for r in (c['ruleSet'] or {}).get('rules', []):
            md = (r.get('conditionObject') or {}).get('metafieldDefinition')
            rule = {'column': r['column'], 'relation': r['relation'], 'condition': r['condition']}
            if md:
                key = f"{md['namespace']}.{md['key']}"
                if key not in defs:
                    raise SystemExit(f"target has no metafield definition {key} (needed by {c['handle']})")
                rule['conditionObjectId'] = defs[key]
            rules.append(rule)
        c['_input'] = {k: v for k, v in {
            'handle': c['handle'], 'title': c['title'], 'sortOrder': c['sortOrder'],
            'descriptionHtml': c['descriptionHtml'], 'templateSuffix': c['templateSuffix'] or None,
            'image': c['image'] and {'src': c['image']['url'], 'altText': c['image']['altText']},
            'seo': c['seo'] if any((c['seo'] or {}).values()) else None,
            'ruleSet': c['ruleSet'] and {'appliedDisjunctively': c['ruleSet']['appliedDisjunctively'], 'rules': rules},
        }.items() if v not in (None, '')}
        print(f"  create {c['handle']:48s} {c['title']}  ({' & '.join(r['condition'] for r in rules)})")

    pages = must(dst, Q_PAGES)

    def resolve(kind, ref_handle, title):
        pool = pages['pages' if kind == 'PAGE' else 'blogs']['nodes']
        for p in pool:
            if p['handle'] == ref_handle:
                return p
        for p in pool:
            if p['title'].strip().lower() == title.strip().lower():
                return p
        raise SystemExit(f'target has no {kind.lower()} matching {ref_handle!r} / {title!r}')

    if not args.apply:
        for h in copy_menus:
            print(f'  menu   {h}')
        print('\ndry run: nothing written')
        return

    # ---- collections -------------------------------------------------------
    online_store = next(p['id'] for p in must(dst, Q_PUBS)['publications']['nodes'] if p['name'] == 'Online Store')
    log = open(os.path.join(ROOT, 'backups', 'dev-write-log.jsonl'), 'a')

    def record(**kw):
        log.write(json.dumps({'ts': datetime.datetime.now().isoformat(timespec='seconds'),
                              'store': target['myshopifyDomain'], **kw}) + '\n')
        log.flush()

    for c in to_create:
        made = must(dst, M_CREATE, {'input': c['_input']})['collectionCreate']['collection']
        existing[made['handle']] = made['id']
        must(dst, M_PUBLISH, {'id': made['id'], 'p': online_store})
        record(action='collectionCreate', handle=made['handle'], id=made['id'], published='Online Store')
        print(f"  created {made['handle']}")

    # Collection metafields: the description and the child-collection list the
    # model template renders. Children are re-pointed at the target's own ids.
    for h, c in wanted.items():
        mfs = []
        if c['description'] and c['description']['value']:
            mfs.append({'ownerId': existing[h], 'namespace': 'custom', 'key': 'category_description',
                        'type': 'multi_line_text_field', 'value': c['description']['value']})
        kids = [n['handle'] for n in ((c['children'] or {}).get('references') or {}).get('nodes', [])]
        if kids:
            mfs.append({'ownerId': existing[h], 'namespace': 'custom', 'key': 'category_collections',
                        'type': 'list.collection_reference', 'value': json.dumps([existing[k] for k in kids])})
        if mfs:
            must(dst, M_METAFIELDS, {'m': mfs})
            record(action='metafieldsSet', handle=h, keys=[m['key'] for m in mfs])

    # ---- menus -------------------------------------------------------------
    current = {m['handle']: m for m in must(dst, Q_MENUS)['menus']['nodes']}
    stamp = datetime.date.today().isoformat()
    snap = os.path.join(ROOT, 'backups', f'dev-menus-before-mirror-{stamp}.json')
    json.dump(list(current.values()), open(snap, 'w'), indent=1)
    print(f'  snapshot of target menus: {os.path.relpath(snap, ROOT)}')

    def convert(items):
        out = []
        for i in items:
            n = {'title': i['title'], 'type': i['type'], 'url': i['url']}
            if i['type'] == 'COLLECTION':
                n['resourceId'] = existing[handle_of(i['url'])]
                n['url'] = f"/collections/{handle_of(i['url'])}"
            elif i['type'] in ('PAGE', 'BLOG'):
                p = resolve(i['type'], handle_of(i['url']), i['title'])
                n['resourceId'] = p['id']
                n['url'] = f"/{'pages' if i['type'] == 'PAGE' else 'blogs'}/{p['handle']}"
            elif i['type'] not in ('COLLECTIONS', 'HTTP', 'SEARCH', 'CATALOG', 'FRONTPAGE'):
                raise SystemExit(f"unsupported menu item type {i['type']} ({i['title']})")
            if i.get('items'):
                n['items'] = convert(i['items'])
            out.append(n)
        return out

    for h in copy_menus:
        ref = ref_menus[h]
        items = convert(ref['items'])
        if h in current:
            must(dst, M_MENU, {'id': current[h]['id'], 'title': ref['title'], 'handle': h, 'items': items})
        else:
            must(dst, M_MENU_NEW, {'title': ref['title'], 'handle': h, 'items': items})
        record(action='menuUpdate' if h in current else 'menuCreate', handle=h, snapshot=os.path.relpath(snap, ROOT))
        print(f'  menu {h} {"updated" if h in current else "created"}')


def _walk(items):
    for i in items or []:
        yield i
        yield from _walk(i.get('items'))


if __name__ == '__main__':
    main()
