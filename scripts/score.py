"""正解集とモデルの判定を比べる。「約束あり」= concrete+vague として適合率・再現率を出し、concrete だけの数字も出す。
使い方: python scripts/score.py <gold.jsonl> <pred.jsonl> [...]"""
import sys, json, collections
def load(p): return {d['cid']: d for d in map(json.loads, open(p, encoding='utf-8'))}
gold = load(sys.argv[1])
def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0; r = tp / (tp + fn) if tp + fn else 0
    return p, r, (2 * p * r / (p + r) if p + r else 0)
print(f'正解: {collections.Counter(g["label"] for g in gold.values())}')
for path in sys.argv[2:]:
    pred = load(path); missing = sum(1 for c in gold if not pred.get(c, {}).get('label'))
    for name, pos in (('約束あり', {'concrete', 'vague'}), ('具体のみ', {'concrete'})):
        tp = fp = fn = 0
        for c, g in gold.items():
            y = g['label'] in pos; yh = (pred.get(c, {}).get('label') in pos)
            tp += y and yh; fp += (not y) and yh; fn += y and not yh
        p, r, f = prf(tp, fp, fn)
        print(f'{path.split("/")[-1]:55s} {name} 適合率{p:.2f} 再現率{r:.2f} F1 {f:.2f} (正{tp} 誤検出{fp} 見逃し{fn}) 無回答{missing}')
