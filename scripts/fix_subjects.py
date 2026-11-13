"""サイトに出す件名を、文脈を渡して付け直す（表示用。約束をまとめる処理には使わない）。
約束の文・前の文・直前の議員の質問を渡し、「何についての約束か」が分かる件名を返させる。20件で1リクエスト。
使い方: python scripts/fix_subjects.py [--limit N]  → data/subject_ai.json（{代表のcid: 件名}。済んだものは飛ばす）"""
import json, glob, pathlib, sys, argparse
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import sakura
from extract_commitments import units

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'subject_ai.json'
PER = 20
MODEL = 'preview/gemma-4-31B-it'
SYSTEM = """あなたは北海道議会の会議録を読む調査員です。
道の執行部が「これから検討する」と答えた約束が、番号つきでいくつか渡されます。それぞれに、一覧に表示する件名を付けてください。

決まりごと：
- 件名を読むだけで、何について（分野・対象・制度や計画の名前）の約束かが分かるようにする。25字以内
- 「必要な対策」「直面する課題」「様々な取組」「施策」のような、どの分野にも当てはまる言葉だけの件名にしない。質問や前の文から、対象を補う（例：物価高の影響緩和に向けた対策、ヒグマ捕獲従事者の確保育成）
- 約束の文・前の文・質問に書かれていないことは足さない
- 道政の良し悪しの評価は書かない
- 文末は名詞で終える（「〜の検討」「〜の見直し」など）
- 渡されたすべての番号 n について1つずつ答える"""
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['results'], 'properties': {'results': {'type': 'array', 'items': {
    'type': 'object', 'additionalProperties': False, 'required': ['n', 'subject'], 'properties': {
        'n': {'type': 'integer'}, 'subject': {'type': 'string'}}}}}}

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--limit', type=int, default=0); a = ap.parse_args()
    items = json.load(open(ROOT / 'site' / 'data.json', encoding='utf-8'))['items']
    done = json.load(open(OUT, encoding='utf-8')) if OUT.exists() else {}
    C = {}
    for f in glob.glob(str(ROOT / 'data' / 'cand' / '*.jsonl')):
        for l in open(f, encoding='utf-8'):
            d = json.loads(l); C[d['cid']] = d
    Q = {}
    for s in {i['session'] for i in items}:
        for u in units(s): Q[u['id']] = u['question']
    todo = [i for i in items if i['id'] not in done]
    batches = [todo[k:k + PER] for k in range(0, len(todo), PER)]
    if a.limit: batches = batches[:a.limit]
    print(f'{len(todo)} 件 → {len(batches)} リクエスト', file=sys.stderr)
    for bi, b in enumerate(batches):
        blocks = []
        for n, i in enumerate(b):
            c = C.get(i['id'], {})
            blocks.append(f'<約束 n="{n}">\n今の件名：{i["subject"]}\n答弁：{i["speaker"]}\n直前の質問（末尾）：{Q.get(c.get("answer_id", ""), "")[-200:]}\n'
                          f'前の文：{c.get("prev", "")[-150:]}\n約束の文：{i["sentence"][:300]}\n</約束>')
        tag = f'subject:{b[0]["id"]}'
        try:
            content, _ = sakura.chat(MODEL, [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': '\n\n'.join(blocks)}],
                                     tag=tag, schema=SCHEMA, temperature=0)
            with open(ROOT / 'data' / 'raw_responses.jsonl', 'a', encoding='utf-8') as rf:
                rf.write(json.dumps({'tag': tag, 'content': content}, ensure_ascii=False) + '\n')
            res = {r['n']: r['subject'].strip() for r in json.loads(content)['results']}
        except Exception as e:
            print('失敗', bi, str(e)[:120], file=sys.stderr); continue
        for n, i in enumerate(b):
            if res.get(n): done[i['id']] = res[n][:40]
        OUT.write_text(json.dumps(done, ensure_ascii=False, indent=0), encoding='utf-8')
        print(bi, len(res), file=sys.stderr)
