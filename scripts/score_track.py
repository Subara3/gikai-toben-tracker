"""追跡の採点。使い方: python scripts/score_track.py <gold.jsonl> <track.v2.jsonl>
- マスごと（約束×あとの会議）の一致率
- 言及あり/なしの見逃し・誤検出（検索と判定のどちらで落ちたかも分ける）
- 最新の状態（サイトに出す値）の一致率"""
import sys, json, collections
gold = {d['cid']: d for d in map(json.loads, open(sys.argv[1], encoding='utf-8'))}
pred = {}
for d in map(json.loads, open(sys.argv[2], encoding='utf-8')):
    for m in d.get('members', [d['cid']]): pred[m] = d   # まとめた約束のどの文でも引けるようにする
def latest(tl): return next((t['status'] for t in reversed(tl) if t['status'] != '言及なし'), '言及なし')
def reached(tl):
    """到達点：一度でも実施・決定なら実施・決定（その会議も返す）。なければ最後の言及。"""
    for t in tl:
        if t['status'] == '実施・決定': return ('実施・決定', t['session'])
    return (latest(tl), '')
cells = agree = 0; rch = rch_s = 0; conf = collections.Counter(); men = collections.Counter(); lat = 0
for cid, g in gold.items():
    p = pred[cid]; pt = {t['session']: t for t in p['timeline']}
    for gt in g['timeline']:
        ps = pt.get(gt['session'], {}).get('status', '言及なし'); gs = gt['status']
        cells += 1; agree += gs == ps; conf[(gs, ps)] += 1
        gm, pm = gs != '言及なし', ps != '言及なし'
        men['正しく言及あり' if gm and pm else '見逃し' if gm else '誤検出' if pm else '正しく言及なし'] += 1
    lat += latest(g['timeline']) == latest(p['timeline'])
    a_, b_ = reached(g['timeline']), reached(p['timeline'])
    rch += a_[0] == b_[0]; rch_s += a_ == b_
print(f'約束 {len(gold)} 件、マス {cells}')
print(f'マスの一致率 {agree / cells:.2f}')
print('言及の有無', dict(men))
tp, fn, fp = men['正しく言及あり'], men['見逃し'], men['誤検出']
print(f'  言及ありの再現率 {tp / (tp + fn):.2f}  適合率 {tp / (tp + fp):.2f}' if tp else '')
both = [(g, p) for (g, p), n in conf.items() for _ in range(n) if g != '言及なし' and p != '言及なし']
print(f'両方が言及ありのマスで状態が一致 {sum(g == p for g, p in both)}/{len(both)}')
print(f'最新の状態の一致 {lat}/{len(gold)}')
print(f'到達点の一致 {rch}/{len(gold)}（決まった会議まで一致 {rch_s}/{len(gold)}）')
print('取り違え（正解→AI）:', {f'{g}→{p}': n for (g, p), n in conf.most_common() if g != p})
