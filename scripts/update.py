"""差分更新：新しい会議の会議録が出たときに、その会議の分だけを調べる。
- これまでの約束（data/track/*.v4.jsonl）それぞれについて、新しい会議の答弁から候補を拾う
- 検索の最高点が SKIP_SCORE 未満、または件名との重なりが SKIP_OVERLAP 未満の約束は、AIに渡さず「言及なし」
- 残りを PER_REQ 件ずつまとめて、1回のリクエストで判定する
使い方: python scripts/update.py <新しい会議 例 honkaigi_R08-3> [--limit N]
出力: data/track_inc/<新しい会議>.jsonl（1行＝約束1件の、その会議での状態）"""
import json, glob, pathlib, sys, argparse, re
import numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import sakura
from sessions import ORDER, LABEL
from track import load_chunks, commitments, fix_quote, KW_WEIGHT, OVERLAP_MIN, STATUSES
from extract_commitments import MEMBER
from terms import overlap

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_SCORE, SKIP_OVERLAP = 0.60, 0.30
PER_REQ = 5
PER_CAND = 6

SYSTEM = """あなたは北海道議会の会議録を読む調査員です。
過去の会議で道の執行部が「これから検討する」と答えた約束がいくつかと、ひとつの新しい会議の答弁の抜粋が、約束ごとに渡されます。
約束ごとに、新しい会議でどういう状態だったかを、抜粋だけを根拠に次の5つから1つ選んでください。
同じ件かどうかは件名で判断します（約束の文の言い回しが違っても、件名と同じものについての答弁なら同じ件）。

- 実施・決定：検討の結果が出たことを、何が（計画・制度・予算・条例・運用・事業の名前）いつ（策定した、示した、始めた、改正した）と具体的に述べている
- 取組中：同じ件について「推進している」「取り組んでいる」「進めている」と述べるだけで、何が決まったかは書かれていない
- 検討継続：同じ件について、まだ検討中・調整中・協議中と述べている
- 見送り：検討の結果、やらない・見送る・取りやめたと述べている
- 言及なし：抜粋に、この約束と同じ件の発言がない（似た話題でも別の件なら言及なし）

決まりごと：
- 抜粋に書かれていないことを推測で補わない。迷ったら「言及なし」
- 執行部の答弁だけを根拠にする
- 骨子・素案・案を示した段階も「実施・決定」。予算に計上した・確保したと述べていれば「実施・決定」
- 担当部や目的が違う答弁は、言葉が似ていても別の件（言及なし）
- その件の具体名（計画名・制度名・事業名・場所）に触れず、分野の一般的な取組を述べているだけなら言及なし
- 「〜すると述べた」「〜していく考え」のような予定だけなら実施・決定にしない（検討継続か取組中）
- 言及なし以外のときは、根拠にした抜粋の番号 k と、その抜粋から一字も変えずに写した引用 quote（40〜120字、途中を省略しない）を付ける
- 言及なし のときは k は -1、quote は空文字
- summary は、その会議で何が言われたかを事実だけで40字以内。道政の良し悪しの評価は書かない
- 渡されたすべての約束 n について1つずつ答える"""

SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['results'], 'properties': {'results': {'type': 'array', 'items': {
    'type': 'object', 'additionalProperties': False, 'required': ['n', 'status', 'k', 'quote', 'summary'], 'properties': {
        'n': {'type': 'integer'}, 'status': {'type': 'string', 'enum': STATUSES},
        'k': {'type': 'integer'}, 'quote': {'type': 'string'}, 'summary': {'type': 'string'}}}}}}


def tracked_before(new):
    """新しい会議より前に約束した件（まとめた代表）と、その埋め込み"""
    out = []
    for f in sorted(glob.glob(str(ROOT / 'data' / 'track' / '*.gemma-4-31B-it.v4.jsonl'))):
        sess = pathlib.Path(f).name.split('.')[0]
        if ORDER[sess] >= ORDER[new]: continue
        Cs = commitments(sess, 'gemma-4-31B-it', '.kijun2'); ci = {c['cid']: i for i, c in enumerate(Cs)}
        Q = np.load(ROOT / 'data' / 'emb' / f'commit_{sess}.gemma-4-31B-it.kijun2.npy').astype(np.float32)
        sj = ROOT / 'data' / 'emb' / f'subject_{sess}.gemma-4-31B-it.kijun2.subjai.npy'  # 付け直した件名（あれば）
        if not sj.exists(): sj = ROOT / 'data' / 'emb' / f'subject_{sess}.gemma-4-31B-it.kijun2.npy'
        QS = np.load(sj).astype(np.float32)
        for d in map(json.loads, open(f, encoding='utf-8')):
            g = [ci[x] for x in d['members']]
            out.append({**d, 'q': Q[g].mean(0), 'qs': QS[g[0]], 'prev': Cs[g[0]].get('prev', '')})
    return out


def stem(kid): return kid.split('#')[0]


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('new'); ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--model', default='preview/gemma-4-31B-it')
    ap.add_argument('--new-stems', default='', help='あとから足されたPDF（例 honkaigi_R08-4_03,honkaigi_R08-4_04）。'
                    '前の結果がある約束は、拾った抜粋にこのPDFの塊が入ったものだけを判定し直す')
    ap.add_argument('--plan', action='store_true', help='AIを呼ばずに、何回かかるかだけを出す')
    a = ap.parse_args()
    new_stems = set(a.new_stems.split(',')) if a.new_stems else None
    K, V = load_chunks()
    m = np.array([k['session'] == a.new and not MEMBER.search(k['speaker']) for k in K])
    idx = np.where(m)[0]; Vn = V[idx]; Kn = [K[i] for i in idx]; Tn = [k['text'] for k in Kn]
    items = tracked_before(a.new)
    out = ROOT / 'data' / 'track_inc' / f'{a.new}.jsonl'; out.parent.mkdir(exist_ok=True)
    prev = {r['cid']: r for r in map(json.loads, open(out, encoding='utf-8'))} if out.exists() else {}
    rows = {}  # cid → その会議での状態（判定のたびに、約束の並び順でファイルを書き直す）

    def save():
        with open(out, 'w', encoding='utf-8') as f:
            for d in items:
                r = rows.get(d['cid']) or prev.get(d['cid'])
                if r: f.write(json.dumps(r, ensure_ascii=False) + '\n')

    todo, skipped, kept = [], 0, 0
    for d in items:
        if new_stems is None and d['cid'] in prev:  # 途中で止まったときの続き
            rows[d['cid']] = prev[d['cid']]; continue
        kw = np.array([overlap(d['subject'], t) for t in Tn], dtype=np.float32)
        sc = np.maximum(d['q'] @ Vn.T, d['qs'] @ Vn.T) + KW_WEIGHT * kw
        if sc.max() < SKIP_SCORE or kw.max() < SKIP_OVERLAP:
            rows[d['cid']] = {'cid': d['cid'], 'session': a.new, 'status': '言及なし', 'skipped': True}
            skipped += 1; continue
        top = np.argsort(-sc)[:PER_CAND]
        p = prev.get(d['cid'])
        # 新しいPDFの塊が抜粋に入らない＝判定の材料が変わらないので、前の判定のまま
        if new_stems is not None and p and not p.get('skipped') and not any(stem(Kn[j]['kid']) in new_stems for j in top):
            rows[d['cid']] = p; kept += 1; continue
        todo.append((d, [Kn[j] for j in top], kw))
    if a.plan:
        print(json.dumps({'requests': (len(todo) + PER_REQ - 1) // PER_REQ}))
        sys.exit(0)
    save()
    print(f'約束 {len(items)} 件：AIに渡さず言及なし {skipped} 件、前の判定のまま {kept} 件、AIに渡す {len(todo)} 件 → {(len(todo) + PER_REQ - 1) // PER_REQ} リクエスト', file=sys.stderr)
    batches = [todo[i:i + PER_REQ] for i in range(0, len(todo), PER_REQ)]
    if a.limit: batches = batches[:a.limit]
    tagm = a.model.split('/')[-1]
    for bi, b in enumerate(batches):
        blocks = []
        for n, (d, cand, _) in enumerate(b):
            ex = '\n'.join(f'  [{k}]（{c["speaker"]}）{c["text"]}' for k, c in enumerate(cand))
            blocks.append(f'<約束 n="{n}">\n件名：{d["subject"]}\n約束した会議：{LABEL[d["session"]]}\n答弁：{d["speaker"]}\n'
                          f'前の文：{d["prev"]}\n約束の文：{d["sentence"]}\n新しい会議（{LABEL[a.new]}）の抜粋：\n{ex}\n</約束>')
        tag = f'update:{a.new}:{tagm}:{b[0][0]["cid"]}'
        try:
            content, usage = sakura.chat(a.model, [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': '\n\n'.join(blocks)}],
                                         tag=tag, schema=SCHEMA, temperature=0)
            with open(ROOT / 'data' / 'raw_responses.jsonl', 'a', encoding='utf-8') as rf:
                rf.write(json.dumps({'tag': tag, 'content': content}, ensure_ascii=False) + '\n')
            res = {r['n']: r for r in json.loads(content)['results']}
        except Exception as e:
            print('失敗', bi, str(e)[:120], file=sys.stderr); continue  # 前の判定があれば、それが残る
        for n, (d, cand, kw) in enumerate(b):
            r = res.get(n) or {'status': '言及なし', 'k': -1, 'quote': '', 'summary': ''}
            ev = cand[r['k']] if 0 <= r['k'] < len(cand) else None
            q, fixed = fix_quote(r['quote'], ev['text']) if ev else (None, False)
            ov = overlap(d['subject'], ev['text']) if ev else 0.0
            st = r['status'] if (r['status'] == '言及なし' or (q and ov >= OVERLAP_MIN)) else '言及なし'
            rows[d['cid']] = {'cid': d['cid'], 'session': a.new, 'status': st, 'model_status': r['status'],
                'summary': r['summary'] if st != '言及なし' else '', 'overlap': round(ov, 2),
                'evidence': ({'kid': ev['kid'], 'speaker': ev['speaker'], 'quote': q, 'quote_fixed': fixed} if st != '言及なし' else None)}
        save()
        print(bi, [res.get(n, {}).get('status', '?')[:2] for n in range(len(b))], file=sys.stderr)
