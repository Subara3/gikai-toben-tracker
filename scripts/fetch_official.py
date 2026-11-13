"""北海道議会公式サイト（CC-BY）の会議録PDFを取得する。1秒ずつ間を空ける。
gijiroku.com の /voices/cgi/ は robots.txt で禁止されているので使わない。"""
import urllib.request, urllib.parse, re, time, json, pathlib, sys
BASE = 'https://www.gikai.pref.hokkaido.lg.jp'
PAGES = {
    'honkaigi_R08-2': '/kaigiroku/kaigiroku_sokuhou/honkaigi/8-2t.html',
    'honkaigi_R08-3': '/kaigiroku/kaigiroku_sokuhou/honkaigi/8-3t.html',
    'yosan_R07-2': '/kaigiroku/kaigiroku_sokuhou/yosan/234625.html',
    'yosan_R07-3': '/kaigiroku/kaigiroku_sokuhou/yosan/241645.html',
    'yosan_R07-4': '/kaigiroku/kaigiroku_sokuhou/yosan/249442.html',
    'yosan_R08-1': '/kaigiroku/kaigiroku_sokuhou/yosan/261927.html',
    'yosan_R08-2': '/kaigiroku/kaigiroku_sokuhou/yosan/269466.html',
    'kessan_R07': '/kaigiroku/kaigiroku_sokuhou/kessan/kaigiroku.html',
}
UA = {'User-Agent': 'Mozilla/5.0 (gikai-tsuiseki; personal research)'}
def get(u): time.sleep(1); return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read()
out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
manifest = []
for key, path in PAGES.items():
    html = get(BASE + path).decode('utf-8', 'replace')
    links = re.findall(r'<a[^>]+href="(/fs/[^"]+\.pdf)"[^>]*>(.*?)</a>', html, re.S)
    for i, (h, label) in enumerate(links, 1):
        label = re.sub(r'<[^>]+>|\s+', ' ', label).strip()
        name = f'{key}_{i:02d}.pdf'
        dst = out / name
        if not dst.exists():
            dst.write_bytes(get(BASE + h))
        manifest.append({'file': name, 'session': key, 'label': label, 'url': BASE + h, 'page': BASE + path})
    print(key, len(links))
(out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
