"""答弁を文に切り、「これからやる」と言っている文を候補として出す（AIを使わない一段目）。
使い方: python scripts/candidates.py <セッション名>  → data/cand/<セッション名>.jsonl"""
import sys, json, re, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from extract_commitments import units, ROOT

FUTURE = re.compile(r'(?:まいり|参り)(?:ます|たい)|まいる考え|いく考え|考え(?:で(?:あり|ござい)ます|です)|予定(?:で(?:あり|ござい)ます|です|としております)|こととして(?:おり|ござい)ます|お示し(?:し|いた)|検討|研究|見直')
PAST = re.compile(r'(?:いたしました|しました|ました|ております)。$')

def sentences(text):
    return [s + '。' for s in re.split(r'。', text) if s.strip()]

if __name__ == '__main__':
    session = sys.argv[1]
    out = ROOT / 'data' / 'cand' / f'{session}.jsonl'; out.parent.mkdir(exist_ok=True)
    n = 0
    with open(out, 'w', encoding='utf-8') as f:
        for u in units(session):
            ss = sentences(u['text'])
            for k, s in enumerate(ss):
                if FUTURE.search(s):
                    n += 1
                    f.write(json.dumps({'cid': f"{u['id']}.{k}", 'answer_id': u['id'], 'speaker': u['speaker'],
                        'asker': u['asker'], 'prev': ''.join(ss[max(0, k - 2):k]).strip()[-200:], 'sentence': s.strip()}, ensure_ascii=False) + '\n')
    print(session, '候補文', n)
