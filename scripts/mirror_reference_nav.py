#!/usr/bin/env python3
"""
Mirror the reference store's header and footer menus, and the collections
they link to, onto the dev store, so the COLLECTIONS mega menu and the footer
columns match the reference.

The reference store is only read. Writes go to the --to store, which must be
a development store: the script refuses to write to production.

Collections are smart collections on the custom.model and
custom.product_category metafield definitions. Both stores define those, so
each copied rule is re-pointed at the target's own definition and fills itself
with the target's matching products. Existing handles on the target are left
alone, which makes re-runs safe.

Menus copied: main-menu, the per-column menus the mega menu looks up
(sportster, softail, ...), and every menu a block in sections/footer-group.json
renders (company, support and the brand row). Page links resolve to the
target's page with the same handle, else the same page template, else the same
title, so they land on the target's equivalent page rather than a copy. Menus
whose content already matches are skipped. Before any write, the target's
menus are snapshotted to a new timestamped file in backups/.

  python3 scripts/mirror_reference_nav.py                 # dry run
  python3 scripts/mirror_reference_nav.py --apply
"""
import argparse, datetime, json, os, sys, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backup_live import Shop, load_env, ROOT
from mirror_theme_images import files_by_name

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
  before: metafield(namespace:"custom", key:"before_image"){ reference{ ... on MediaImage{ image{ url } } } }
} }'''
Q_DEFS = '{ metafieldDefinitions(first:100, ownerType:PRODUCT){ nodes{ id namespace key } } }'
Q_COLL_DEFS = '{ metafieldDefinitions(first:100, ownerType:COLLECTION){ nodes{ name namespace key type{ name } } } }'
Q_COLL_MF = '''query($id:ID!){ collection(id:$id){
  category_description: metafield(namespace:"custom", key:"category_description"){ value }
  category_collections: metafield(namespace:"custom", key:"category_collections"){ value }
  before_image: metafield(namespace:"custom", key:"before_image"){ value } } }'''
M_DEF = '''mutation($d:MetafieldDefinitionInput!){ metafieldDefinitionCreate(definition:$d){
  createdDefinition{ id } userErrors{ field message } } }'''
# Collection metafields the model template reads. before_image is bound as the
# slider's AFTER picture in collection.model.json (the reference's naming).
COLLECTION_MF = {'category_description': 'multi_line_text_field',
                 'category_collections': 'list.collection_reference',
                 'before_image': 'file_reference'}
Q_PAGES = '{ pages(first:250){ nodes{ id handle title templateSuffix } } blogs(first:50){ nodes{ id handle title } } }'
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
    # The mega menu looks each column up as linklists[column.title | handleize];
    # the footer blocks name their menu in a setting.
    copy_menus = ['main-menu'] + [c['title'].strip().lower().replace(' ', '-')
                                  for top in main_menu['items'] for c in top['items'] or []]
    copy_menus += footer_menus()
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

    # ---- collection metafields: definitions, then values that differ --------
    ref_defs = [d for d in must(src, Q_COLL_DEFS)['metafieldDefinitions']['nodes']
                if d['namespace'] == 'custom' and d['key'] in COLLECTION_MF]
    have_defs = {(d['namespace'], d['key']) for d in must(dst, Q_COLL_DEFS)['metafieldDefinitions']['nodes']}
    defs_to_create = [d for d in ref_defs if (d['namespace'], d['key']) not in have_defs]
    for d in defs_to_create:
        print(f"  define collection metafield custom.{d['key']} ({d['type']['name']})")

    target_files = files_by_name(dst)

    def metafield_changes():
        out = []
        for h, c in wanted.items():
            want = {}
            if c['description'] and c['description']['value']:
                want['category_description'] = c['description']['value']
            kids = [n['handle'] for n in ((c['children'] or {}).get('references') or {}).get('nodes', [])]
            if kids:
                want['category_collections'] = json.dumps([existing.get(k, f'(new) {k}') for k in kids])
            url = ((((c['before'] or {}).get('reference') or {}).get('image')) or {}).get('url')
            if url:
                name = urllib.parse.unquote(url.split('?')[0].rsplit('/', 1)[-1])
                if name not in target_files:
                    raise SystemExit(f'{h}: target Files has no {name}; copy it first (mirror_theme_images.py)')
                want['before_image'] = target_files[name]['id']
            have = must(dst, Q_COLL_MF, {'id': existing[h]})['collection'] if h in existing else {}
            for key, value in want.items():
                cur = (have.get(key) or {}).get('value')
                same = (json.loads(cur) == json.loads(value)) if cur and key == 'category_collections' else cur == value
                if not same:
                    out.append((h, key, value))
        return out

    mf_plan = metafield_changes()
    for h, key, _ in mf_plan:
        print(f'  metafield {h:40s} custom.{key}')

    pages, ref_pages = must(dst, Q_PAGES), must(src, Q_PAGES)

    def resolve(kind, ref_handle, title):
        key = 'pages' if kind == 'PAGE' else 'blogs'
        pool = pages[key]['nodes']
        ref = next((p for p in ref_pages[key]['nodes'] if p['handle'] == ref_handle), {})
        tests = [lambda p: p['handle'] == ref_handle]
        if ref.get('templateSuffix'):
            tests.append(lambda p: p.get('templateSuffix') == ref['templateSuffix'])
        tests.append(lambda p: p['title'].strip().lower() in
                     {title.strip().lower(), ref.get('title', '').strip().lower()})
        for test in tests:
            hits = [p for p in pool if test(p)]
            if len(hits) == 1:
                return hits[0]
        raise SystemExit(f'target has no single {kind.lower()} matching {ref_handle!r} / {title!r}')

    def convert(items):
        out = []
        for i in items:
            n = {'title': i['title'], 'type': i['type'], 'url': i['url']}
            if i['type'] == 'COLLECTION':
                n['resourceId'] = existing.get(handle_of(i['url']), '(to be created)')
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

    def shape(items):
        return [(i['title'], i['type'], i['url'].rstrip('/'), shape(i.get('items') or [])) for i in items]

    current = {m['handle']: m for m in must(dst, Q_MENUS)['menus']['nodes']}
    menu_plan = []
    for h in copy_menus:
        items = convert(ref_menus[h]['items'])
        same = h in current and shape(current[h]['items']) == shape(items)
        menu_plan.append((h, items, same))
        print(f"  menu   {h:12s} {'unchanged' if same else 'update' if h in current else 'create'}")
        if not same:
            for it in _walk(items):
                print(f"           {it['title']:28s} -> {it['url']}")

    if not args.apply:
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

    # Definitions first: the theme binds custom.before_image as a dynamic source,
    # which Shopify only accepts once a definition exists.
    for d in defs_to_create:
        must(dst, M_DEF, {'d': {'name': d['name'], 'namespace': d['namespace'], 'key': d['key'],
                                'type': d['type']['name'], 'ownerType': 'COLLECTION'}})
        record(action='metafieldDefinitionCreate', owner='COLLECTION', key=f"{d['namespace']}.{d['key']}")
        print(f"  defined custom.{d['key']}")

    # Recomputed now that new collections have ids; children and files are
    # re-pointed at the target's own resources.
    by_handle = {}
    for h, key, value in metafield_changes():
        by_handle.setdefault(h, []).append({'ownerId': existing[h], 'namespace': 'custom', 'key': key,
                                            'type': COLLECTION_MF[key], 'value': value})
    for h, mfs in by_handle.items():
        must(dst, M_METAFIELDS, {'m': mfs})
        record(action='metafieldsSet', handle=h, keys=[m['key'] for m in mfs])
        print(f"  metafields {h}: {', '.join(m['key'] for m in mfs)}")

    # ---- menus -------------------------------------------------------------
    changed = [h for h, _, same in menu_plan if not same]
    if not changed:
        return
    stamp = datetime.datetime.now().strftime('%Y-%m-%dT%H%M%S')
    snap = os.path.join(ROOT, 'backups', f'dev-menus-before-mirror-{stamp}.json')
    json.dump(list(current.values()), open(snap, 'w'), indent=1)
    print(f'  snapshot of target menus: {os.path.relpath(snap, ROOT)}')

    for h in changed:
        ref = ref_menus[h]
        items = convert(ref['items'])  # again: collections created above now have ids
        if h in current:
            must(dst, M_MENU, {'id': current[h]['id'], 'title': ref['title'], 'handle': h, 'items': items})
        else:
            must(dst, M_MENU_NEW, {'title': ref['title'], 'handle': h, 'items': items})
        record(action='menuUpdate' if h in current else 'menuCreate', handle=h, snapshot=os.path.relpath(snap, ROOT))
        print(f'  menu {h} {"updated" if h in current else "created"}')


def footer_menus():
    """Menu handles named by the footer's blocks: the Company and Support
    columns and the brand row."""
    text = open(os.path.join(ROOT, 'sections', 'footer-group.json'), encoding='utf-8').read().strip()
    if text.startswith('/*'):
        text = text[text.index('*/') + 2:]
    out = []
    for section in json.loads(text)['sections'].values():
        out += [b['settings']['menu'] for b in (section.get('blocks') or {}).values()
                if b.get('settings', {}).get('menu')]
    return out


def _walk(items):
    for i in items or []:
        yield i
        yield from _walk(i.get('items'))


if __name__ == '__main__':
    main()
