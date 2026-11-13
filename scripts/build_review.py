"""正解集を人が確かめるためのページを作る。→ review/<名前>.html
使い方: python scripts/build_review.py data/gold_track/R07-4.holdout.jsonl data/gold_track/holdout20_R07-4.jsonl
押した結果はブラウザに一時保存され、「結果を保存」でJSONを書き出す。"""
import json, sys, pathlib, re
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from sessions import LABEL
from build_site import locate, clean

ROOT = pathlib.Path(__file__).resolve().parent.parent
gold_p, src_p = sys.argv[1], sys.argv[2]
src = {d['cid']: d for d in map(json.loads, open(src_p, encoding='utf-8'))}
rows = []
for g in map(json.loads, open(gold_p, encoding='utf-8')):
    s = src[g['cid']]
    tl = []
    for t in g['timeline']:
        r = {'s': t['session'], 'label': LABEL[t['session']], 'st': t['status'], 'q': t.get('quote', '')}
        if t.get('id'): r.update(locate(t['id'], t['quote']))
        tl.append(r)
    rows.append({'cid': g['cid'], 'subject': s['subject'], 'speaker': s['speaker'], 'sentence': clean(s['sentence'], s['speaker']),
                 'src': locate(g['cid'], s['sentence']), 'doubt': g.get('doubt', False), 'note': g.get('note', ''), 'timeline': tl})
name = pathlib.Path(gold_p).stem
out = ROOT / 'review' / f'{name}.html'; out.parent.mkdir(exist_ok=True)
html = (ROOT / 'site_src' / 'review.html').read_text(encoding='utf-8').replace('__DATA__', json.dumps(rows, ensure_ascii=False)).replace('__NAME__', name)
out.write_text(html, encoding='utf-8')
print(out, len(rows), '件')
