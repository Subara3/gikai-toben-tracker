"""約束の「その後」を、あとの会議ごとに追う。
1. 約束（判定結果が concrete / vague の文）を埋め込み、同じ会議の中で近いもの（類似度 GROUP_SIM 以上）を1つにまとめる
2. まとめた約束ごとに、あとの会議それぞれから近い塊を PER_SESSION 件ずつ拾う
3. LLM に、会議ごとの状態（実施・決定／検討継続／見送り／言及なし）と根拠の引用を返させる
4. 引用は原文の中であいまい一致で探し、9割以上一致すれば原文の文字列に置き換える（quote_fixed）。それ未満は捨てて言及なし扱い
使い方: python scripts/track.py <約束の会議 例 yosan_R07-2> <判定モデル> [--limit N]
出力: data/track/<会議>.<モデル>.v2.jsonl（1行＝まとめた約束1件）"""
import json, glob, pathlib, sys, argparse, re, difflib
import numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import sakura
from sessions import ORDER, LABEL
from embed_chunks import MODEL as EMODEL, norm
from extract_commitments import MEMBER
from terms import overlap

ROOT = pathlib.Path(__file__).resolve().parent.parent
GROUP_SIM = 0.88
PER_SESSION = 6
MIN_SIM = 0.45
KW_WEIGHT = 0.3
OVERLAP_MIN = 0.3
STATUSES = ['実施・決定', '取組中', '検討継続', '見送り', '言及なし']

SYSTEM = """あなたは北海道議会の会議録を読む調査員です。
ある会議で道の執行部が「これから検討する」と答えた約束と、その件名、そのあとの会議ごとの発言の抜粋が渡されます。
同じ件かどうかは、件名で判断します（約束の文の言い回しが違っても、件名と同じものについての答弁なら同じ件）。
会議ごとに、その約束がどういう状態だったかを、抜粋だけを根拠に次の5つから1つ選んでください。

- 実施・決定：検討の結果が出たことを、何が（計画・制度・予算・条例・運用・事業の名前）いつ（策定した、示した、始めた、改正した）と具体的に述べている
- 取組中：同じ件について「推進している」「取り組んでいる」「進めている」と述べるだけで、何が決まったかは書かれていない
- 検討継続：同じ件について、まだ検討中・調整中・協議中と述べている
- 見送り：検討の結果、やらない・見送る・取りやめたと述べている
- 言及なし：その会議の抜粋に、この約束と同じ件の発言がない（似た話題でも別の件なら言及なし）

決まりごと：
- 抜粋に書かれていないことを推測で補わない。迷ったら「言及なし」
- 執行部の答弁だけを根拠にする
- 骨子・素案・案を示した段階も「実施・決定」（何の段階かを summary に書く）。予算に計上した・確保したと述べていれば「実施・決定」
- 担当部や目的が違う答弁は、言葉が似ていても別の件（言及なし）。例：防犯の対策と、依存症対策計画の普及啓発は別の件
- その件の具体名（計画名・制度名・事業名・場所）に触れず、分野の一般的な取組を述べているだけなら言及なし
- 言及なし以外のときは、根拠にした抜粋の番号 k と、その抜粋から一字も変えずに写した引用 quote（40〜120字、途中を省略しない）を付ける
- 「〜すると述べた」「〜していく考え」のような予定だけなら実施・決定にしない（検討継続か取組中）
- 言及なし のときは k は -1、quote は空文字
- summary は、その会議で何が言われたかを事実だけで40字以内。道政の良し悪しの評価は書かない
- すべての会議について1つずつ答える"""

SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['sessions'], 'properties': {'sessions': {'type': 'array', 'items': {
    'type': 'object', 'additionalProperties': False, 'required': ['session', 'status', 'k', 'quote', 'summary'], 'properties': {
        'session': {'type': 'string'}, 'status': {'type': 'string', 'enum': STATUSES},
        'k': {'type': 'integer'}, 'quote': {'type': 'string'}, 'summary': {'type': 'string'}}}}}}


def load_chunks():
    K = [json.loads(l) for l in open(ROOT / 'data' / 'chunks.jsonl', encoding='utf-8')]
    files = sorted(glob.glob(str(ROOT / 'data' / 'emb' / 'chunks_500_*.npy')))
    V = np.concatenate([np.load(f).astype(np.float32) for f in files])
    assert len(V) == len(K), f'埋め込み {len(V)} 件と塊 {len(K)} 件が合わない'
    # watch.py があとから足した塊（data/chunks_inc/<PDF名>.jsonl と data/emb/inc_<PDF名>.npy）
    Ks, Vs = [K], [V]
    for p in sorted(glob.glob(str(ROOT / 'data' / 'chunks_inc' / '*.jsonl'))):
        e = ROOT / 'data' / 'emb' / f'inc_{pathlib.Path(p).stem}.npy'
        if not e.exists(): continue
        k = [json.loads(l) for l in open(p, encoding='utf-8')]; v = np.load(e).astype(np.float32)
        assert len(k) == len(v), f'{p} の埋め込みと塊が合わない'
        Ks.append(k); Vs.append(v)
    return [x for k in Ks for x in k], np.concatenate(Vs)


def commitments(session, pred_model, suffix):
    C = {d['cid']: d for d in map(json.loads, open(ROOT / 'data' / 'cand' / f'{session}.jsonl', encoding='utf-8'))}
    out = []
    for p in map(json.loads, open(ROOT / 'data' / 'pred' / f'{session}.{pred_model}.per60{suffix}.jsonl', encoding='utf-8')):
        if p['label'] in ('concrete', 'vague'):
            out.append({**C[p['cid']], 'label': p['label'], 'subject': p['subject'], 'deadline': p['deadline'], 'session': session})
    return out


def group(Cs, Q):
    """近い約束をまとめる（貪欲法）。代表は concrete を優先し、文の長いもの。"""
    order = sorted(range(len(Cs)), key=lambda i: (Cs[i]['label'] != 'concrete', -len(Cs[i]['sentence'])))
    gid = [-1] * len(Cs); groups = []
    for i in order:
        if gid[i] >= 0: continue
        g = [i]; gid[i] = len(groups)
        for j in order:
            if gid[j] < 0 and float(Q[i] @ Q[j]) >= GROUP_SIM:
                gid[j] = gid[i]; g.append(j)
        groups.append(g)
    return groups


def n(s): return re.sub(r'\s', '', s)


def fix_quote(q, text):
    """引用を原文の中で探す。完全一致ならそのまま、9割以上の一致なら原文の該当箇所に置き換える。"""
    if not q: return None, False
    if n(q) in n(text): return q, False
    sm = difflib.SequenceMatcher(None, text, q, autojunk=False)
    m = sm.find_longest_match(0, len(text), 0, len(q))
    # 一致した位置を中心に、引用と同じ長さの窓で比べる
    start = max(0, m.a - m.b); cand = text[start:start + len(q) + 5]
    r = difflib.SequenceMatcher(None, cand, q, autojunk=False).ratio()
    if r >= 0.9:
        end = cand.rfind('。', 0, len(q) + 5)
        return (cand[:end + 1] if end > len(q) * 0.7 else cand[:len(q)]), True
    return None, False


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('session'); ap.add_argument('model')
    ap.add_argument('--pred-model', default='gemma-4-31B-it'); ap.add_argument('--pred-suffix', default='.kijun2')
    ap.add_argument('--limit', type=int, default=0); ap.add_argument('--only', default='', help='代表のcidを並べたファイル')
    ap.add_argument('--out-suffix', default='.v3')
    ap.add_argument('--subjects', default='', help='件名を差し替える（fix_subjects.py の data/subject_ai.json）。検索・重なり・AIに渡す件名に使う')
    ap.add_argument('--replay', default='', help='保存した応答を読み直す。タグの接頭辞（例 track2:yosan_R07-2:gemma-4-31B-it）')
    a = ap.parse_args()
    K, V = load_chunks()
    Cs = commitments(a.session, a.pred_model, a.pred_suffix)
    if a.subjects:  # AIで付け直した件名（カードの代表cidごと）を、同じ追跡行の約束すべてに当てる
        SA = json.load(open(a.subjects, encoding='utf-8')); m = {}
        for l in open(ROOT / 'data' / 'track' / f'{a.session}.gemma-4-31B-it.v4.jsonl', encoding='utf-8'):
            d = json.loads(l)
            if d['cid'] in SA:
                for c in d['members']: m[c] = SA[d['cid']]
        for c in Cs:
            if c['cid'] in m: c['subject'] = m[c['cid']]
        print('件名を差し替えた', sum(c['cid'] in m for c in Cs), '/', len(Cs), file=sys.stderr)
    qp = ROOT / 'data' / 'emb' / f'commit_{a.session}.{a.pred_model}{a.pred_suffix}.npy'
    if qp.exists() and len(np.load(qp)) == len(Cs):
        Q = np.load(qp).astype(np.float32)
    else:
        Q = norm(sakura.embed(EMODEL, [f"{c['subject']}：{c['sentence']}"[:400] for c in Cs], tag=f'embed:commit:{a.session}'))
        np.save(qp, Q.astype(np.float16))
    G = group(Cs, Q)
    sp = ROOT / 'data' / 'emb' / f'subject_{a.session}.{a.pred_model}{a.pred_suffix}{".subjai" if a.subjects else ""}.npy'
    if sp.exists() and len(np.load(sp)) == len(Cs):
        QS = np.load(sp).astype(np.float32)
    else:
        QS = norm(sakura.embed(EMODEL, [c['subject'][:200] or c['sentence'][:200] for c in Cs], tag=f'embed:subject:{a.session}'))
        np.save(sp, QS.astype(np.float16))
    exec_mask = np.array([not MEMBER.search(k['speaker']) for k in K])
    texts = [k['text'] for k in K]
    later_sessions = sorted({k['session'] for k in K if ORDER[k['session']] > ORDER[a.session]}, key=lambda s: (ORDER[s], s))
    print(f'約束 {len(Cs)} 件 → まとめて {len(G)} 件、あとの会議 {len(later_sessions)} 回', file=sys.stderr)
    if not later_sessions:
        # いちばん新しい会議の約束：まだ追う先がないので、AIは呼ばずに一覧だけ書く（次の会議が出たら update.py が追う）。
        # 同じ会議にPDFが足されたら作り直すので、上書きする
        out = ROOT / 'data' / 'track' / f'{a.session}.{a.model.split("/")[-1]}{a.out_suffix}.jsonl'; out.parent.mkdir(exist_ok=True)
        with open(out, 'w', encoding='utf-8') as f:
            for g in G:
                rep = Cs[g[0]]
                f.write(json.dumps({'cid': rep['cid'], 'session': a.session, 'speaker': rep['speaker'], 'asker': rep.get('asker', ''),
                    'subject': rep['subject'], 'deadline': rep['deadline'], 'sentence': rep['sentence'], 'label': rep['label'],
                    'members': [Cs[i]['cid'] for i in g], 'latest': '言及なし', 'timeline': []}, ensure_ascii=False) + '\n')
        print(f'あとの会議がないので、一覧だけ書いた → {out.name}', file=sys.stderr)
        sys.exit(0)
    if a.only:
        want = set(json.loads(l)['cid'] for l in open(a.only, encoding='utf-8'))
        G = [g for g in G if Cs[g[0]]['cid'] in want]
    if a.limit: G = G[:a.limit]
    replay = {}
    a.replay_map = {}
    if a.replay:
        rows_raw = [json.loads(l) for l in open(ROOT / 'data' / 'raw_responses.jsonl', encoding='utf-8')]
        for r in rows_raw: replay[r['tag']] = r['content']   # 同じタグはあとのものが残る
        # 古い形式のタグ（末尾が通し番号）を、代表の cid に対応させる
        for gi0, g0 in enumerate(G): a.replay_map[Cs[g0[0]]['cid']] = f'{a.replay}:{gi0}'
    sess_idx = {s: np.array([k['session'] == s for k in K]) for s in later_sessions}
    tagm = a.model.split('/')[-1]
    out = ROOT / 'data' / 'track' / f'{a.session}.{tagm}{a.out_suffix}.jsonl'; out.parent.mkdir(exist_ok=True)
    done = {json.loads(l)['cid'] for l in open(out, encoding='utf-8')} if out.exists() else set()
    for gi, g in enumerate(G):
        rep = Cs[g[0]]
        if rep['cid'] in done: continue
        subj = rep['subject']
        kw = np.array([overlap(subj, x) for x in texts], dtype=np.float32)
        sims = np.maximum(Q[g].mean(axis=0) @ V.T, QS[g[0]] @ V.T) + KW_WEIGHT * kw
        blocks, cand = [], {}
        for s in later_sessions:
            sc = np.where(sess_idx[s] & exec_mask, sims, -9)
            top = [j for j in np.argsort(-sc)[:PER_SESSION] if sc[j] >= MIN_SIM]
            cand[s] = [K[j] for j in top]
            body = '\n'.join(f'  [{k}]（{K[j]["speaker"]}）{K[j]["text"]}' for k, j in enumerate(top)) or '  （近い発言なし）'
            blocks.append(f'<会議 session="{s}" name="{LABEL[s]}">\n{body}\n</会議>')
        user = (f'<約束>\n会議：{LABEL[a.session]}\n答弁：{rep["speaker"]}\n前の文：{rep.get("prev", "")}\n約束の文：{rep["sentence"]}\n'
                + ''.join(f'同じ件の別の文：{Cs[i]["sentence"]}\n' for i in g[1:3]) + '</約束>\n\n' + '\n\n'.join(blocks))
        tag = f'track2:{a.session}:{tagm}{a.out_suffix}:{rep["cid"]}'
        try:
            if a.replay:  # 保存した応答を読み直す（再リクエストしない）
                content = replay.get(tag) or replay.get(a.replay_map.get(rep['cid'], ''))
                if content is None: print('保存なし', rep['cid'], file=sys.stderr); continue
            else:
                content, usage = sakura.chat(a.model, [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}],
                                             tag=tag, schema=SCHEMA, temperature=0)
                with open(ROOT / 'data' / 'raw_responses.jsonl', 'a', encoding='utf-8') as rf:
                    rf.write(json.dumps({'tag': tag, 'content': content}, ensure_ascii=False) + '\n')
            rows = json.loads(content)['sessions']
        except Exception as e:
            print('失敗', gi, e, file=sys.stderr); continue
        # 会議の欄は識別名（yosan_R07-3）でも表示名（予算特別委 令和7年第3回）でも受け付ける。どちらでもなければ並び順で当てる
        name2key = {LABEL[x]: x for x in later_sessions}
        res = {}
        for idx, r in enumerate(rows):
            key = r['session'] if r['session'] in later_sessions else name2key.get(r['session'].strip())
            if key is None and len(rows) == len(later_sessions): key = later_sessions[idx]
            if key: res[key] = r
        timeline = []
        for s in later_sessions:
            r = res.get(s) or {'status': '言及なし', 'k': -1, 'quote': '', 'summary': ''}
            ev = cand[s][r['k']] if 0 <= r['k'] < len(cand[s]) else None
            q, fixed = fix_quote(r['quote'], ev['text']) if ev else (None, False)
            ov = overlap(subj, ev['text']) if ev else 0.0
            # 根拠が原文で確かめられない、または約束の中心の語との重なりが小さいものは言及なし
            st = r['status'] if (r['status'] == '言及なし' or (q and ov >= OVERLAP_MIN)) else '言及なし'
            timeline.append({'session': s, 'status': st, 'model_status': r['status'], 'summary': r['summary'] if st != '言及なし' else '',
                             'overlap': round(ov, 2), 'evidence': ({'kid': ev['kid'], 'speaker': ev['speaker'], 'quote': q, 'quote_fixed': fixed} if st != '言及なし' else None)})
        latest = next((t['status'] for t in reversed(timeline) if t['status'] != '言及なし'), '言及なし')
        with open(out, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'cid': rep['cid'], 'session': a.session, 'speaker': rep['speaker'], 'asker': rep.get('asker', ''),
                'subject': rep['subject'], 'deadline': rep['deadline'], 'sentence': rep['sentence'], 'label': rep['label'],
                'members': [Cs[i]['cid'] for i in g], 'latest': latest, 'timeline': timeline}, ensure_ascii=False) + '\n')
        print(gi, rep['subject'][:20], '→', [t['status'][:2] for t in timeline], file=sys.stderr)
