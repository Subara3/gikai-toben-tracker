"""同じ件なのに別のカードになっているものを、AIに判定させてまとめる（表示用）。
1. カードごとに「件名（fix_subjects.py で付け直したもの）：約束の文」を埋め込み、近い組（類似度 SIM 以上、各カード上位 TOPK）を候補にする
2. 候補の組を PER 組ずつ gemma に渡し、同じ件かを判定させる
使い方: python scripts/merge_ai.py [--plan] [--limit N]  → data/merge_ai.json（{"pairs": [[cid, cid, true/false], ...]}。済んだ組は飛ばす）"""
import json, pathlib, sys, argparse
import numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import sakura
from embed_chunks import MODEL as EMODEL, norm

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'merge_ai.json'
EMB = ROOT / 'data' / 'emb' / 'cards_subject_ai.npy'
SIM, TOPK, PER = 0.80, 5, 10
MODEL = 'preview/gemma-4-31B-it'
SYSTEM = """あなたは北海道議会の会議録を読む調査員です。
道の執行部が「これから検討する」と答えた約束が、2件ずつの組でいくつか渡されます。組ごとに、2件が同じ件かどうかを判定してください。

同じ件：同じ施策・計画・制度・事業について、検討の結果が出たら両方が同時に片付く関係にあるもの。
- 例：同じ計画の「骨子を示す」と「最終案を取りまとめる」は同じ件
- 例：物価高対策の「必要な対策を検討する」と「影響緩和に向けた対策を検討する」は同じ件
別の件：分野が同じでも、対象や中身が違うもの。
- 例：ヒグマの「捕獲従事者の確保育成」と「ゾーニング管理計画の策定支援」は別の件
- 例：宿泊税の「使途の具体化」と「市町村との制度調整」は別の件
迷ったら別の件にする。渡されたすべての組 n について1つずつ答える。"""
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['results'], 'properties': {'results': {'type': 'array', 'items': {
    'type': 'object', 'additionalProperties': False, 'required': ['n', 'same'], 'properties': {
        'n': {'type': 'integer'}, 'same': {'type': 'boolean'}}}}}}

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--plan', action='store_true'); ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    items = json.load(open(ROOT / 'site' / 'data.json', encoding='utf-8'))['items']
    texts = [f"{i['subject']}：{i['sentence']}"[:400] for i in items]
    if EMB.exists() and len(np.load(EMB)) == len(items):
        Q = np.load(EMB).astype(np.float32)
    else:
        Q = np.concatenate([norm(sakura.embed(EMODEL, texts[k:k + 500], tag=f'embed:cards:{k // 500}')) for k in range(0, len(texts), 500)])
        np.save(EMB, Q.astype(np.float16))
    S = Q @ Q.T; np.fill_diagonal(S, -1)
    pairs = set()
    for x in range(len(items)):
        for y in np.argsort(-S[x])[:TOPK]:
            if S[x, y] >= SIM: pairs.add(tuple(sorted((int(x), int(y)))))
    pairs = sorted(pairs, key=lambda p: -S[p])
    done = {(p[0], p[1]): p[2] for p in json.load(open(OUT, encoding='utf-8'))['pairs']} if OUT.exists() else {}
    todo = [p for p in pairs if tuple(sorted((items[p[0]]['id'], items[p[1]]['id']))) not in done]
    n_req = (len(todo) + PER - 1) // PER
    print(json.dumps({'cards': len(items), 'pairs': len(pairs), 'todo': len(todo), 'requests': n_req}))
    if a.plan: sys.exit(0)
    batches = [todo[k:k + PER] for k in range(0, len(todo), PER)]
    if a.limit: batches = batches[:a.limit]
    def card(i): return f'件名：{i["subject"]}\n会議：{i["session"]}　答弁：{i["speaker"]}\n約束の文：{i["sentence"][:250]}'
    for bi, b in enumerate(batches):
        user = '\n\n'.join(f'<組 n="{n}">\n［1］{card(items[x])}\n［2］{card(items[y])}\n</組>' for n, (x, y) in enumerate(b))
        tag = f'merge:{items[b[0][0]]["id"]}'
        try:
            content, _ = sakura.chat(MODEL, [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}],
                                     tag=tag, schema=SCHEMA, temperature=0)
            with open(ROOT / 'data' / 'raw_responses.jsonl', 'a', encoding='utf-8') as rf:
                rf.write(json.dumps({'tag': tag, 'content': content}, ensure_ascii=False) + '\n')
            res = {r['n']: r['same'] for r in json.loads(content)['results']}
        except Exception as e:
            print('失敗', bi, str(e)[:120], file=sys.stderr); continue
        for n, (x, y) in enumerate(b):
            if n in res: done[tuple(sorted((items[x]['id'], items[y]['id'])))] = res[n]
        OUT.write_text(json.dumps({'pairs': [[k[0], k[1], v] for k, v in done.items()]}, ensure_ascii=False), encoding='utf-8')
        print(bi, sum(res.values()), '/', len(b), file=sys.stderr)
