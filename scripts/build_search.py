"""全文検索用の索引を作る。会議録の全部の発言（執行部の答弁・議員の質問・議事進行）を、会議ごとに gzip した JSON にする。
→ site/search/index.json, site/search/<会議>.json.gz（ブラウザで DecompressionStream を使って展開して探す）
AIは使わない。塊は track.py と同じ（data/chunks.jsonl ＋ watch.py があとから足した data/chunks_inc/*.jsonl）。"""
import json, glob, gzip, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from sessions import ORDER, LABEL
from build_site import MAN, pages

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'site' / 'search'
CHAIR = re.compile(r'^副?議長|議長君?$|委員長$')
OFFICIAL = re.compile(r'選挙管理委員|監査委員|人事委員|公安委員|教育委員|労働委員|収用委員')  # 答弁する側の委員
MEMBER = re.compile(r'委員$|^\d+番|番.+君$')
SKIP = re.compile(r'^(本日の|出席|欠席|説明員|会議録|日程|事務局|開会|散会|休憩|再開)')


def role(speaker):
    if OFFICIAL.search(speaker): return 'a'
    if CHAIR.search(speaker): return 'c'   # 議長・委員長（議事進行）
    if MEMBER.search(speaker): return 'q'  # 議員
    if SKIP.search(speaker) or len(speaker) > 30: return 'o'  # 名簿・日程など
    return 'a'                              # 執行部（知事・部長など）


def page_of(stem, text):
    key = re.sub(r'\s', '', text)
    for probe in (key[:24], key[10:34], key[-24:]):
        if len(probe) < 8: continue
        for i, t in enumerate(pages(stem)):
            if probe in t: return i + 1
    return 0


def chunks():
    K = [json.loads(l) for l in open(ROOT / 'data' / 'chunks.jsonl', encoding='utf-8')]
    for p in sorted(glob.glob(str(ROOT / 'data' / 'chunks_inc' / '*.jsonl'))):
        K += [json.loads(l) for l in open(p, encoding='utf-8')]
    return K


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    by = {}
    seen = set()
    for k in chunks():
        if k['kid'] in seen: continue  # 同じPDFを取り直したときの重なり
        seen.add(k['kid']); by.setdefault(k['session'], []).append(k)
    index = []
    for s in sorted(by, key=lambda x: (ORDER[x], x)):
        stems = sorted({k['kid'].split('#')[0] for k in by[s]})
        pdfs = [{'url': MAN[f'{st}.pdf']['url'], 'date': MAN[f'{st}.pdf']['label'].split(' (PDF')[0].split('（PDF')[0].strip()} for st in stems]
        si = {st: i for i, st in enumerate(stems)}
        rows = [[si[k['kid'].split('#')[0]], page_of(k['kid'].split('#')[0], k['text']), role(k['speaker']), k['speaker'], k['text']]
                for k in by[s]]
        data = json.dumps({'pdfs': pdfs, 'rows': rows}, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        f = f'{s}.json.gz'
        (OUT / f).write_bytes(gzip.compress(data, 9, mtime=0))
        index.append({'key': s, 'label': LABEL[s], 'order': ORDER[s], 'file': f, 'n': len(rows),
                      'from': pdfs[0]['date'], 'to': pdfs[-1]['date']})
        print(s, len(rows), '塊', round(len(data) / 1e6, 1), 'MB →', round((OUT / f).stat().st_size / 1e6, 2), 'MB', file=sys.stderr)
    (OUT / 'index.json').write_text(json.dumps({'sessions': index}, ensure_ascii=False), encoding='utf-8')
    print('全文検索の索引', sum(x['n'] for x in index), '塊 →', OUT)
