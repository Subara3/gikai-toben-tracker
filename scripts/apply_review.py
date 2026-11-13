"""本人が review/R07-4.holdout.html で確かめた結果（review_R07-4.holdout.json）を正解集に反映し、測り直す。
- 「合っている」→ そのまま、「違う」→ 選んだ正しい状態（fix）に直す。押していないマスはそのまま（件数を出す）
- 出力：data/gold_track/R07-4.holdout.checked.jsonl と、score_track.py での採点
使い方: python scripts/apply_review.py <review_R07-4.holdout.json>"""
import json, sys, pathlib, subprocess, glob
ROOT = pathlib.Path(__file__).resolve().parent.parent
GOLD = ROOT / 'data' / 'gold_track' / 'R07-4.holdout.jsonl'
OUT = ROOT / 'data' / 'gold_track' / 'R07-4.holdout.checked.jsonl'

ans = json.load(open(sys.argv[1], encoding='utf-8'))
n_ok = n_fix = n_none = 0
changes = []
with open(OUT, 'w', encoding='utf-8') as f:
    for g in map(json.loads, open(GOLD, encoding='utf-8')):
        for t in g['timeline']:
            a = ans.get(f"{g['cid']}|{t['session']}")
            if not a or 'ok' not in a: n_none += 1; continue
            if a['ok']: n_ok += 1; continue
            if a.get('fix') and a['fix'] != t['status']:
                changes.append((g['cid'], t['session'], t['status'], a['fix'])); t['status'] = a['fix']; t['checked_fix'] = True
            n_fix += 1
        f.write(json.dumps(g, ensure_ascii=False) + '\n')
print(f'合っている {n_ok}、違う {n_fix}（直した {len(changes)}）、未確認 {n_none}')
for c in changes: print('  直した', *c)
track = sorted(glob.glob(str(ROOT / 'data' / 'track' / 'yosan_R07-4.gemma-4-31B-it.v4.jsonl')))[0]
for gold in (GOLD, OUT):
    print('===', pathlib.Path(gold).name)
    subprocess.run([sys.executable, str(ROOT / 'scripts' / 'score_track.py'), str(gold), track])
