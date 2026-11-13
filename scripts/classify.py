"""二段目：候補文ごとに「検討の約束」かを判定させる。文は番号で渡し、番号とラベルだけ返させる（引用させない）。
使い方: python scripts/classify.py <セッション名> <モデル> [--per N] [--limit N]"""
import sys, json, pathlib, argparse, re
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import sakura
ROOT = pathlib.Path(__file__).resolve().parent.parent
CRIT = (ROOT / 'notes' / '判定基準.md').read_text(encoding='utf-8')
SYSTEM = ('あなたは北海道議会の会議録を読む調査員です。渡される各文が、道の執行部による「これから検討する」という約束かどうかを、次の基準で判定します。\n\n'
          + CRIT + '\n\n各文に label（concrete / vague / none）を付けて返してください。concrete と vague には subject（何を検討するか、30字以内）と deadline（時期の語句だけ、なければ空文字）も付けます。none の subject と deadline は空文字。全部の文に答えること。〔前の文〕は判定の参考で、判定するのは「判定する文」だけです。')
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['results'], 'properties': {'results': {'type': 'array', 'items': {
    'type': 'object', 'additionalProperties': False, 'required': ['n', 'label', 'subject', 'deadline'], 'properties': {
        'n': {'type': 'integer'}, 'label': {'type': 'string', 'enum': ['concrete', 'vague', 'none']},
        'subject': {'type': 'string'}, 'deadline': {'type': 'string'}}}}}}

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('session'); ap.add_argument('model')
    ap.add_argument('--per', type=int, default=60); ap.add_argument('--limit', type=int, default=0); ap.add_argument('--suffix', default=''); ap.add_argument('--sys-in-user', action='store_true')
    a = ap.parse_args()
    C = [json.loads(l) for l in open(ROOT / 'data' / 'cand' / f'{a.session}.jsonl', encoding='utf-8')]
    tagm = a.model.split('/')[-1]
    out = ROOT / 'data' / 'pred' / f'{a.session}.{tagm}.per{a.per}{a.suffix}.jsonl'; out.parent.mkdir(exist_ok=True)
    prev = [json.loads(l) for l in open(out, encoding='utf-8')] if out.exists() else []
    done = {d['cid'] for d in prev if d['label']}
    if len(done) < len(prev):  # 失敗したチャンクの行を消して、回し直す
        with open(out, 'w', encoding='utf-8') as f:
            for d in prev:
                if d['label']: f.write(json.dumps(d, ensure_ascii=False) + '\n')
    chunks = [C[i:i + a.per] for i in range(0, len(C), a.per)]
    if a.limit: chunks = chunks[:a.limit]
    def ask(ci, ch, depth=0):
        """1チャンクを判定する。サーバのタイムアウトなどで失敗したら半分に分けて送り直す（2段まで）。"""
        user = '\n'.join(f'[{k}]（{c["speaker"]}）' + (f'〔前の文：{c["prev"]}〕' if c.get('prev') else '')
                         + f'\n判定する文：{c["sentence"]}' for k, c in enumerate(ch))
        tag = f'classify:{a.session}:{tagm}:{ci}' + (f'.{depth}' if depth else '')
        try:
            msgs = ([{'role': 'user', 'content': SYSTEM + '\n\n---\n\n' + user}] if a.sys_in_user
                    else [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}])
            content, usage = sakura.chat(a.model, msgs, tag=tag, schema=SCHEMA, temperature=0)
            with open(ROOT / 'data' / 'raw_responses.jsonl', 'a', encoding='utf-8') as rf:
                rf.write(json.dumps({'tag': tag, 'content': content}, ensure_ascii=False) + '\n')
            rs = json.loads(content)['results']
            # 1文ずつ渡したときは番号を見ない（llm-jp は渡していない番号を返すことがある）
            return {0: rs[0]} if len(ch) == 1 and len(rs) >= 1 else {r['n']: r for r in rs}
        except Exception as e:
            print('失敗', tag, str(e)[:120], file=sys.stderr)
            if depth < 2 and len(ch) > 10:
                h = len(ch) // 2
                r1 = ask(ci, ch[:h], depth + 1); r2 = ask(ci, ch[h:], depth + 1)
                return {**r1, **{k + h: v for k, v in r2.items()}}
            return {}
    for ci, ch in enumerate(chunks):
        if all(c['cid'] in done for c in ch): continue
        res = ask(ci, ch)
        with open(out, 'a', encoding='utf-8') as f:
            for k, c in enumerate(ch):
                r = res.get(k)
                f.write(json.dumps({'cid': c['cid'], 'label': r['label'] if r else None,
                    'subject': r['subject'] if r else '', 'deadline': r['deadline'] if r else ''}, ensure_ascii=False) + '\n')
        print(ci, len(ch), '文 → 回答', len(res), file=sys.stderr)
