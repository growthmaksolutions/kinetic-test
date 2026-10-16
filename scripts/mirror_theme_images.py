#!/usr/bin/env python3
"""
Copy the Files-library images the theme's settings point at from the
reference store to the dev store, under the same filenames.

Image settings in JSON templates, section groups and settings_data.json are
stored as shopify://shop_images/<filename>, which resolves against the
current store's Files library. The dev store never had the reference store's
uploads, so those settings resolved to nothing and each section fell back to
its bundled asset. That is why the homepage before/after sliders all showed
the same half-drawn Sportster.

Only files the target is missing are copied. Each is created from the
reference store's CDN URL with its exact filename, and duplicate names raise
an error instead of getting a suffix, because a renamed copy would not match
the setting. The reference store is only read, and the script refuses to
write unless the target is a development store.

  python3 scripts/mirror_theme_images.py            # dry run
  python3 scripts/mirror_theme_images.py --apply
"""
import argparse, datetime, json, os, re, sys, time, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backup_live import Shop, load_env, ROOT

Q_FILES = '''query($c:String){ files(first:250, after:$c){ nodes{ id fileStatus alt
  ... on MediaImage{ image{ url } } ... on GenericFile{ url } }
  pageInfo{ hasNextPage endCursor } } }'''
M_FILE = '''mutation($files:[FileCreateInput!]!){ fileCreate(files:$files){
  files{ id fileStatus } userErrors{ field message code } } }'''
REF = re.compile(r'shopify://shop_images/([^"\s]+)')


def files_by_name(shop):
    out, cur = {}, None
    while True:
        d = shop.call(Q_FILES, {'c': cur})
        if d is None:
            raise SystemExit(f'files query failed: {shop.denied[-1] if shop.denied else "unknown"}')
        for n in d['files']['nodes']:
            url = (n.get('image') or {}).get('url') or n.get('url')
            if url:
                name = urllib.parse.unquote(url.split('?')[0].rsplit('/', 1)[-1])
                out[name] = {'id': n['id'], 'url': url, 'alt': n.get('alt'), 'status': n['fileStatus']}
        if not d['files']['pageInfo']['hasNextPage']:
            return out
        cur = d['files']['pageInfo']['endCursor']


def theme_image_refs():
    """filename -> theme files that reference it."""
    refs = {}
    for folder in ('templates', 'sections', 'config'):
        for name in sorted(os.listdir(os.path.join(ROOT, folder))):
            if name.endswith('.json'):
                text = open(os.path.join(ROOT, folder, name), encoding='utf-8').read()
                for m in REF.findall(text):
                    refs.setdefault(urllib.parse.unquote(m), set()).add(f'{folder}/{name}')
    return refs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='src', default=os.path.join(ROOT, '.env.live'))
    ap.add_argument('--to', dest='dst', default=os.path.join(ROOT, '.env'))
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    src, dst = Shop(load_env(args.src)), Shop(load_env(args.dst))
    target = dst.call('{ shop{ myshopifyDomain plan{ partnerDevelopment } } }')['shop']
    if not target['plan']['partnerDevelopment']:
        raise SystemExit(f"refusing to write: {target['myshopifyDomain']} is not a development store")
    print(f"mode: {'APPLY' if args.apply else 'DRY RUN'}  target: {target['myshopifyDomain']}")

    refs = theme_image_refs()
    have, ref_files = files_by_name(dst), files_by_name(src)
    missing = sorted(n for n in refs if n not in have)
    # Some stores convert uploads (avif -> jpg). If the target already holds
    # the same image under another extension, uploading again only adds a
    # uuid-suffixed duplicate that still cannot match the setting.
    stems = {os.path.splitext(h)[0]: h for h in have}
    converted = [n for n in missing if os.path.splitext(n)[0] in stems]
    missing = [n for n in missing if n not in converted]
    unknown = [n for n in missing if n not in ref_files]
    print(f'images referenced by theme settings: {len(refs)}  on target: {len(refs) - len(missing) - len(converted)}'
          f'  to copy: {len(missing)}  converted on target: {len(converted)}')
    for n in converted:
        print(f"  SKIP   {n}: target stores it as {stems[os.path.splitext(n)[0]]}, so the setting cannot resolve "
              f"({', '.join(sorted(refs[n]))}); re-pick the image in the theme editor")
    for n in missing:
        print(f"  {'copy  ' if n in ref_files else 'ABSENT'} {n}  ({', '.join(sorted(refs[n]))})")
    if unknown:
        raise SystemExit(f'not on the reference store either: {unknown}')
    if not args.apply or not missing:
        print('\ndry run: nothing written' if not args.apply else '\nnothing to copy')
        return

    log = open(os.path.join(ROOT, 'backups', 'dev-write-log.jsonl'), 'a')
    for n in missing:
        f = ref_files[n]
        d = dst.call(M_FILE, {'files': [{'originalSource': f['url'], 'contentType': 'IMAGE', 'filename': n,
                                         'alt': f['alt'] or '', 'duplicateResolutionMode': 'RAISE_ERROR'}]})
        res = (d or {}).get('fileCreate') or {}
        if not d or res.get('userErrors'):
            raise SystemExit(f'fileCreate failed for {n}: {res.get("userErrors") or dst.denied[-1:]}')
        log.write(json.dumps({'ts': datetime.datetime.now().isoformat(timespec='seconds'),
                              'store': target['myshopifyDomain'], 'action': 'fileCreate',
                              'filename': n, 'id': res['files'][0]['id'], 'source': 'reference store'}) + '\n')
        print(f'  uploaded {n}')
    log.close()

    # Files process asynchronously; a setting only resolves once its file is READY.
    for _ in range(30):
        have = files_by_name(dst)
        pending = [n for n in missing if have.get(n, {}).get('status') != 'READY']
        if not pending:
            print(f'all {len(missing)} files READY under their original names')
            return
        time.sleep(5)
    raise SystemExit(f'not READY (or stored under a different name): {pending}')


if __name__ == '__main__':
    main()
