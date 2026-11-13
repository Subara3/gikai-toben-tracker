"""追跡結果から静的サイトを作る。→ site/index.html, site/data.json
使い方: python scripts/build_site.py [--suffix .v4]
- 約束と根拠の引用ごとに、原文PDFの何ページにあるかを探して #page= 付きのリンクにする
- 道政の評価は書かない。状態と原文の引用だけを並べる"""
import json, glob, re, pathlib, sys, argparse, shutil
import fitz
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from sessions import ORDER, LABEL

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / 'site'
MAN = {m['file']: m for m in json.load(open(ROOT / 'data' / 'raw' / 'pdf' / 'manifest.json', encoding='utf-8'))}
_pages = {}

_ovp = ROOT / 'data' / 'overrides.json'
OVR = json.load(open(_ovp, encoding='utf-8')) if _ovp.exists() else {'merge': [], 'subject': {}}
_sap = ROOT / 'data' / 'subject_ai.json'
SUBJ_AI = json.load(open(_sap, encoding='utf-8')) if _sap.exists() else {}
_map = ROOT / 'data' / 'merge_ai.json'
EXCLUDE = {c for c, _ in OVR.get('exclude', [])}  # [cid, 外した理由]
MERGE_AI = json.load(open(_map, encoding='utf-8'))['pairs'] if _map.exists() else []  # [cid, cid, 同じ件か]
_askers = {}
MEMBER_Q = re.compile(r'委員$|^\d+番|番.+君$')
OFFICIAL = re.compile(r'選挙管理委員|監査委員|人事委員|公安委員|教育委員|労働委員|収用委員')
GOV = re.compile(r'(^|[^副])知事')

def asker_of(speech_id):
    """答弁（発言id 例 yosan_R07-3_04#123）の直前に質問した議員"""
    stem = speech_id.split('#')[0]
    if stem not in _askers:
        last, m = '', {}
        for i, l in enumerate(open(ROOT / 'data' / 'text' / f'{stem}.jsonl', encoding='utf-8')):
            sp = json.loads(l)['speaker']
            if MEMBER_Q.search(sp) and not OFFICIAL.search(sp) and not re.search(r'委員長$', sp): last = sp
            m[f'{stem}#{i}'] = last
        _askers[stem] = m
    return _askers[stem].get(speech_id, '')

def person(sp):
    """「72番真下紀子君」「畠山みのり委員」→ 名前だけ"""
    return re.sub(r'^\d+番|君$|委員$', '', sp).strip()

def pages(stem):
    if stem not in _pages:
        d = fitz.open(ROOT / 'data' / 'raw' / 'pdf' / f'{stem}.pdf')
        _pages[stem] = [re.sub(r'\s', '', p.get_text()) for p in d]
    return _pages[stem]

def locate(any_id, text):
    """発言id（例 yosan_R07-3_04#123 や その塊 .3）と引用から、PDFのURLとページを返す"""
    stem = any_id.split('#')[0]
    m = MAN[f'{stem}.pdf']
    key = re.sub(r'\s', '', text)
    pg = None
    for probe in (key[:24], key[10:34], key[-24:]):
        if len(probe) < 8: continue
        for i, t in enumerate(pages(stem)):
            if probe in t: pg = i + 1; break
        if pg: break
    return {'url': m['url'] + (f'#page={pg}' if pg else ''), 'page': pg, 'date': m['label'].split(' (PDF')[0].split('（PDF')[0].strip()}

def clean(sentence, speaker):
    """答弁の頭に残った「○阿部経済部参与」のような発言者名を取り除く"""
    s = sentence.strip()
    if s.startswith('○'):
        s = s[1:]
        if s.startswith(speaker): s = s[len(speaker):]
        else: s = re.sub(r'^\S{2,14}?(参与|理事|監|長|委員)', '', s, count=1)
    return s

def reached(tl):
    for t in tl:
        if t['status'] == '実施・決定': return '実施・決定', t['session']
    last = next((t for t in reversed(tl) if t['status'] != '言及なし'), None)
    return (last['status'], last['session']) if last else ('言及なし', '')

RANK = {'実施・決定': 4, '見送り': 3, '検討継続': 2, '取組中': 1, '言及なし': 0}
MERGE_SENT, MERGE_SUBJ = 0.80, 0.90

_inc = None
def merge_inc(d):
    """差分更新の結果（data/track_inc/*.jsonl）を時系列に足す。同じ会議がすでにあれば、進んだほうの状態を残す"""
    global _inc
    if _inc is None:
        _inc = {}
        for p in sorted(glob.glob(str(ROOT / 'data' / 'track_inc' / '*.jsonl'))):
            for r in map(json.loads, open(p, encoding='utf-8')):
                _inc.setdefault(r['cid'], {})[r['session']] = r
    for s, r in _inc.get(d['cid'], {}).items():
        old = next((t for t in d['timeline'] if t['session'] == s), None)
        if old is None: d['timeline'].append(r)
        elif RANK[r['status']] > RANK[old['status']]: d['timeline'][d['timeline'].index(old)] = r

def load_tracked(suffix):
    """追跡結果と、約束の文・件名の埋め込みを読む"""
    import numpy as np
    from track import commitments
    from terms import bigrams
    items, Vs, Vj = [], [], []
    for f in sorted(glob.glob(str(ROOT / 'data' / 'track' / f'*.gemma-4-31B-it{suffix}.jsonl'))):
        sess = pathlib.Path(f).name.split('.')[0]
        Cs = commitments(sess, 'gemma-4-31B-it', '.kijun2'); idx = {c['cid']: i for i, c in enumerate(Cs)}
        Q = np.load(ROOT / 'data' / 'emb' / f'commit_{sess}.gemma-4-31B-it.kijun2.npy').astype(np.float32)
        QS = np.load(ROOT / 'data' / 'emb' / f'subject_{sess}.gemma-4-31B-it.kijun2.npy').astype(np.float32)
        for d in map(json.loads, open(f, encoding='utf-8')):
            if d['cid'] in EXCLUDE: continue  # 判定基準で約束に当たらないと手で判断したもの（overrides.json の exclude）
            merge_inc(d)
            i = idx[d['cid']]; items.append(d); Vs.append(Q[i]); Vj.append(QS[i])
            d['_q'], d['_qs'] = Q[[idx[c] for c in d['members'] if c in idx]].mean(0), QS[i]  # 関連発言の検索に使う
    Vs, Vj = np.array(Vs), np.array(Vj)
    ok = [d['label'] == 'concrete' and len(bigrams(d['subject'])) >= 2 for d in items]
    SS, SJ = Vs @ Vs.T, Vj @ Vj.T
    par = list(range(len(items)))
    def f(x):
        while par[x] != x: par[x] = par[par[x]]; x = par[x]
        return x
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if ok[i] and ok[j] and SS[i, j] >= MERGE_SENT and SJ[i, j] >= MERGE_SUBJ: par[f(i)] = f(j)
    # 手で指定した「同じ件」（data/overrides.json の merge）
    at = {}
    for i, d in enumerate(items):
        for c in [d['cid'], *d.get('members', [])]: at.setdefault(c, i)
    for m in OVR.get('merge', []):  # 手で指定したもの
        idx = [at[c] for c in m if c in at]
        for j in idx[1:]: par[f(j)] = f(idx[0])
    # AIが同じ件と判定した組（merge_ai.py）。つながった先に、AIが「別の件」と判定した組が入るならまとめない
    sep = {frozenset(p) for p in OVR.get('separate', [])}  # 手で「別の件」と指定した組
    diff = [(at[x], at[y]) for x, y, same in MERGE_AI + [[*p, False] for p in OVR.get('separate', [])]
            if not same and x in at and y in at]
    for x, y, same in MERGE_AI:
        if not same or x not in at or y not in at or frozenset((x, y)) in sep: continue
        rx, ry = f(at[x]), f(at[y])
        if rx == ry: continue
        if any({f(u), f(v)} == {rx, ry} for u, v in diff): continue
        par[ry] = rx
    groups = {}
    for i in range(len(items)): groups.setdefault(f(i), []).append(items[i])
    return list(groups.values())

def card(members):
    """会議をまたいで同じ件の約束をまとめた1件。会議ごとに、いちばん進んだ状態を出す"""
    members = sorted(members, key=lambda d: (ORDER[d['session']], d['cid']))
    first = members[0]
    promises = []
    for d in members:
        # まとめた約束ごとの状態（大きなカードで、まだ決まっていない約束が見えるように）
        st1, at1 = reached(sorted([{'session': t['session'], 'status': t['status']} for t in d['timeline']
                                   if ORDER[t['session']] > ORDER[d['session']]], key=lambda t: ORDER[t['session']]))
        promises.append({'cid': d['cid'], 'session': d['session'], 'speaker': d['speaker'], 'asker': d.get('asker', ''),
                         'sentence': clean(d['sentence'], d['speaker']), 'src': locate(d['cid'], d['sentence']),
                         'subject': SUBJ_AI.get(d['cid']) or d['subject'], 'st': st1, 'at': at1,
                         'later': sum(1 for t in d['timeline'] if ORDER[t['session']] > ORDER[d['session']])})
    promised = {d['session'] for d in members}
    # 約束が出た会議でも、それより前の約束から見た状態は残す（あとの会議で再び約束したことも印を付ける）
    sessions = sorted({t['session'] for d in members for t in d['timeline']}, key=lambda s: (ORDER[s], s))
    tl, ev_people = [], []
    for s in sessions:
        best = None
        for d in members:
            if ORDER[s] <= ORDER[d['session']]: continue
            t = next((x for x in d['timeline'] if x['session'] == s), None)
            if t and (best is None or RANK[t['status']] > RANK[best['status']]): best = t
        if best is None: continue
        row = {'s': s, 'st': best['status'], 'sum': best.get('summary', ''), 'again': s in promised}
        e = best.get('evidence')
        if e:
            row.update({'who': e['speaker'], 'q': e['quote'], **locate(e['kid'], e['quote'])})
            ev_people.append((e['speaker'], asker_of(e['kid'].rsplit('.', 1)[0])))
        tl.append(row)
    st, at = reached([{'session': r['s'], 'status': r['st']} for r in tl])
    # 件名：手で直したもの → AIで付け直したもの（fix_subjects.py）→ 最初の約束の件名
    ids = [d['cid'] for d in members] + [c for d in members for c in d.get('members', [])]
    subj = (next((OVR['subject'][c] for c in ids if c in OVR.get('subject', {})), None)
            or SUBJ_AI.get(first['cid']) or next((SUBJ_AI[c] for c in ids if c in SUBJ_AI), None) or first['subject'])
    # 重みの手がかり（AIは使わず数えるだけ）：取り上げられた会議の数、質問した議員の数、知事が答えたか
    talked = promised | {r['s'] for r in tl if r['st'] != '言及なし'}
    askers = {person(a) for a in [d.get('asker', '') for d in members] + [a for _, a in ev_people] if a}
    gov = any(GOV.search(x) for x in [d['speaker'] for d in members] + [w for w, _ in ev_people])
    return {'id': first['cid'], 'session': first['session'], 'subject': subj, 'speaker': first['speaker'],
            'asker': first.get('asker', ''), 'sentence': promises[0]['sentence'], 'src': promises[0]['src'],
            'promises': promises, 'reached': st, 'reached_at': at, 'timeline': tl,
            'nses': len(talked), 'nask': len(askers), 'gov': gov}

REL_SIM, REL_N, REL_KW = 0.50, 2, 0.30

def related(groups, items):
    """「言及なし」の会議ごとに、その会議で埋め込みが近い発言（議員の質問も含む）を REL_N 件まで拾う（AIの判定はしない）。
    → site/rel.json.gz（{件のid: {会議: [[役割, 発言者, PDFのURL, 抜粋], ...]}}。件を開いたときにブラウザが読む）"""
    import numpy as np, gzip
    from track import load_chunks
    from build_search import role
    from terms import overlap
    K, V = load_chunks()
    sess_of = np.array([k['session'] for k in K])
    byid = {}
    for g in groups:
        for d in g: byid.setdefault(d['cid'], g)
    out = {}
    for it in items:
        g = byid[it['id']] if it['id'] in byid else next(g for g in groups if any(it['id'] in [d['cid'], *d.get('members', [])] for d in g))
        q = np.mean([d['_q'] for d in g], 0); qs = np.mean([d['_qs'] for d in g], 0)
        sims = np.maximum(V @ q, V @ qs)
        rel = {}
        for t in it['timeline']:
            if t['st'] != '言及なし': continue
            sc = np.where(sess_of == t['s'], sims, -9)
            # 埋め込みで近い20件のうち、件名の語との重なりがあるものだけを、重なりを足した点で並べる
            cand = [j for j in np.argsort(-sc)[:20] if sc[j] >= REL_SIM and role(K[j]['speaker']) in ('a', 'q')]
            kw = {j: overlap(it['subject'], K[j]['text']) for j in cand}
            top = sorted([j for j in cand if kw[j] >= REL_KW], key=lambda j: -(sc[j] + 0.3 * kw[j]))[:REL_N]
            rows = []
            for j in top:
                k = K[j]; stem = k['kid'].split('#')[0]; m = MAN[f'{stem}.pdf']
                pg = locate(k['kid'], k['text'])['page']
                rows.append([role(k['speaker']), k['speaker'], m['url'] + (f'#page={pg}' if pg else ''), k['text'][:160]])
            if rows: rel[t['s']] = rows
        if rel: out[it['id']] = rel
    (SITE / 'rel.json.gz').write_bytes(gzip.compress(json.dumps(out, ensure_ascii=False, separators=(',', ':')).encode(), 9, mtime=0))
    print('関連発言', sum(len(v) for v in out.values()), '会議分 →', round((SITE / 'rel.json.gz').stat().st_size / 1e6, 2), 'MB', file=sys.stderr)

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--suffix', default='.v4'); a = ap.parse_args()
    groups = load_tracked(a.suffix)
    # いちばん新しい会議で初めて出た約束は、あとの会議が出るまで載せない（前の約束とまとまったものは「再び約束」として載る）
    items = [card(g) for g in groups if any(d['timeline'] for d in g)]
    items.sort(key=lambda i: (ORDER[i['session']], i['id']))
    SITE.mkdir(exist_ok=True)
    meta = {'sessions': {k: {'label': LABEL[k], 'order': ORDER[k]} for k in LABEL}, 'count': len(items),
            'promises': sum(len(i['promises']) for i in items),
            'built': (lambda t: f'{t.year}年{t.month}月{t.day}日')(__import__('datetime').date.today())}
    (SITE / 'data.json').write_text(json.dumps({'meta': meta, 'items': items}, ensure_ascii=False), encoding='utf-8')
    related(groups, items)
    for f in ('index.html', 'search.html', 'og.png'): shutil.copy(ROOT / 'site_src' / f, SITE / f)
    print('約束', meta['promises'], '件 → まとめて', len(items), '件 → site/')
