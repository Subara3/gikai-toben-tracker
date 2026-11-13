"""検索だけの評価（LLMを使わない）。正解集の根拠の発言が、会議ごとの候補に入るかを数える。"""
import json, sys, re, numpy as np, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import sakura
from track import load_chunks, commitments, group, ORDER
from embed_chunks import MODEL as EMODEL, norm
from extract_commitments import MEMBER

GENERIC = set('検討 在り方 あり方 取組 取り組み 推進 対応 見直し 必要 効果的 今後 具体的 様々 取りまとめ 方針 施策 対策 実施 充実 強化 確保 向上 促進 支援 体制 整備 活用 連携 検証 点検 必要な 新た 新たな 本道 道内 全体 より 効率的 さらなる 関係 状況 内容 計画'.split())

def key_terms(subject):
    parts = re.split(r'[のをにへとでや、・（）「」\s]|における|に係る|に関する|に向けた|について|による', subject)
    return [p for p in parts if len(p) >= 2 and p not in GENERIC]

if __name__ == '__main__':
    K, V = load_chunks()
    exec_mask = np.array([not MEMBER.search(k['speaker']) for k in K])
    Cs = commitments('yosan_R07-2', 'gemma-4-31B-it', '.kijun2')
    Q = np.load('data/emb/commit_yosan_R07-2.gemma-4-31B-it.kijun2.npy').astype(np.float32)
    G = group(Cs, Q); rep = {Cs[g[0]]['cid']: g for g in G}
    gold = [json.loads(l) for l in open('data/gold_track/R07-2.claude-draft.jsonl', encoding='utf-8')]
    # 「何を」だけの埋め込み（30件ぶん、1リクエスト）
    sp = pathlib.Path('data/emb/subject_gold30.npy')
    if sp.exists(): QS = np.load(sp).astype(np.float32)
    else:
        QS = norm(sakura.embed(EMODEL, [Cs[rep[g['cid']][0]]['subject'] for g in gold], tag='embed:subject:gold30')); np.save(sp, QS.astype(np.float16))
    sess = {s: np.array([k['session'] == s for k in K]) for s in {k['session'] for k in K}}
    texts = [k['text'] for k in K]
    def run(name, scorer, n, only_exec):
        hit = tot = 0; ncand = 0
        for gi, g in enumerate(gold):
            grp = rep[g['cid']]; sc = scorer(gi, grp)
            for t in g['timeline']:
                if t['status'] == '言及なし': continue
                m = sess[t['session']] & (exec_mask if only_exec else True)
                s2 = np.where(m, sc, -9); top = np.argsort(-s2)[:n]
                ncand += n; tot += 1; hit += any(K[j]['kid'].rsplit('.', 1)[0] == t['id'] for j in top)
        print(f'{name:40s} 候補{n:2d}/会議  根拠の発言が候補に入った {hit}/{tot} = {hit / tot:.2f}')
    sent = lambda gi, grp: Q[grp].mean(axis=0) @ V.T
    subj = lambda gi, grp: QS[gi] @ V.T
    both = lambda gi, grp: np.maximum(Q[grp].mean(axis=0) @ V.T, QS[gi] @ V.T)
    def kw(gi, grp):
        terms = key_terms(Cs[grp[0]]['subject'])
        bonus = np.array([sum(t in x for t in terms) for x in texts], dtype=np.float32) / max(1, len(terms))
        return both(gi, grp) + 0.3 * bonus
    for n in (3, 6):
        run('文の埋め込み（いま）', sent, n, False)
        run('文の埋め込み・答弁だけ', sent, n, True)
        run('「何を」の埋め込み・答弁だけ', subj, n, True)
        run('両方の大きいほう・答弁だけ', both, n, True)
        run('両方＋語句一致・答弁だけ', kw, n, True)
