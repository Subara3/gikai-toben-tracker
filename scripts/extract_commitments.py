"""答弁から「これから検討する」型の約束を抜き出す。
使い方: python scripts/extract_commitments.py <セッション名 例 yosan_R07-2> <モデル> [--limit N]
1リクエストに答弁を詰め込む（MAX_CHARS まで）。抜き出した quote が原文に本当にあるかはコードで確かめる。"""
import sys, json, glob, re, pathlib, argparse
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import sakura

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEMBER = re.compile(r'委員$|副委員長$|委員長$|議長君$|議長$|^\d+番|番.+君$')
MAX_CHARS = 14000

SYSTEM = """あなたは北海道議会の会議録を読む調査員です。
渡される答弁（知事・副知事・部長・局長・課長・教育長など執行部の発言）から、「これから何かを検討する・見直す・結論を出す・示す」と将来の行動を約束した文だけを抜き出します。

抜き出すもの：
- 「検討してまいります」「検討を進めてまいります」「見直しを検討」「研究してまいります」「〜までにお示しします」「協議してまいります」のように、まだ決まっていないことを今後決める・調べる・示すと述べた文

抜き出さないもの：
- 「努めてまいります」「取り組んでまいります」「進めてまいります」だけで、すでに行っている事業を続けるという文
- 国や他団体が検討しているという紹介
- 過去にやったことの説明

quote には答弁の原文の1文を、一字も変えずにそのまま入れること（句点「。」まで）。要約や言い換えをしない。
該当がない答弁は出力に含めない。"""

SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['items'], 'properties': {'items': {'type': 'array', 'items': {
    'type': 'object', 'additionalProperties': False,
    'required': ['answer_id', 'quote', 'subject', 'kind', 'deadline'],
    'properties': {
        'answer_id': {'type': 'string'},
        'quote': {'type': 'string', 'description': '原文の1文をそのまま'},
        'subject': {'type': 'string', 'description': '何を検討するか。30字以内の名詞句'},
        'kind': {'type': 'string', 'enum': ['検討', '研究', '見直し', '提示', '協議', 'その他']},
        'deadline': {'type': 'string', 'description': '時期を表す語句だけ（例：次期定例会、７月中、年度内）。なければ空文字'}}}}}}

def units(session):
    out = []
    for f in sorted(glob.glob(str(ROOT / 'data' / 'text' / f'{session}_*.jsonl'))):
        L = [json.loads(l) for l in open(f, encoding='utf-8')]
        last_q = None
        for s in L:
            if MEMBER.search(s['speaker']):
                if len(s['text']) > 40: last_q = s
                continue
            if len(s['text']) < 40: continue
            out.append({'id': s['id'], 'speaker': s['speaker'], 'text': s['text'],
                        'asker': last_q['speaker'] if last_q else '', 'question': (last_q['text'][-300:] if last_q else '')})
    return out

def batches(us):
    b, n = [], 0
    for u in us:
        size = len(u['text']) + len(u['question']) + 80
        if b and n + size > MAX_CHARS: yield b; b, n = [], 0
        b.append(u); n += size
    if b: yield b

def norm(s): return re.sub(r'\s', '', s)

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('session'); ap.add_argument('model'); ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    us = units(a.session); bs = list(batches(us))
    print(f'答弁 {len(us)} 件 → {len(bs)} リクエスト', file=sys.stderr)
    if a.limit: bs = bs[:a.limit]
    tagm = a.model.split('/')[-1]
    outp = ROOT / 'data' / 'commit' / f'{a.session}.{tagm}.jsonl'; outp.parent.mkdir(exist_ok=True)
    done = set()
    if outp.exists():
        for l in open(outp, encoding='utf-8'): done.add(json.loads(l)['batch'])
    byid = {u['id']: u for u in us}
    for i, b in enumerate(bs):
        if i in done: continue
        user = '\n\n'.join(f'<answer id="{u["id"]}" speaker="{u["speaker"]}">\n（直前の質問の末尾：{u["question"]}）\n{u["text"]}\n</answer>' for u in b)
        content, usage = sakura.chat(a.model, [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}],
                                     tag=f'extract:{a.session}:{i}', schema=SCHEMA, temperature=0)
        try: items = json.loads(content)['items']
        except Exception: items = []; print('JSON失敗', i, content[:200], file=sys.stderr)
        for it in items:
            u = byid.get(it['answer_id'])
            it['quote_found'] = bool(u and norm(it['quote']).rstrip('。') in norm(u['text']))
            if u: it['speaker'] = u['speaker']; it['asker'] = u['asker']
        with open(outp, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'batch': i, 'ids': [u['id'] for u in b], 'items': items, 'usage': usage}, ensure_ascii=False) + '\n')
        print(i, len(b), '答弁 →', len(items), '件', 'quote不一致', sum(not x['quote_found'] for x in items), usage.get('total_tokens'), file=sys.stderr)
