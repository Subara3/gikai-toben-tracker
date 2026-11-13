"""答弁に出てくる「検討してまいります」型の約束を数える（下見用。本番の抽出はLLM）。"""
import json, glob, re, collections, pathlib
PAT = re.compile(r'[^。]*?(検討して(?:まいり|参り)ます|検討を進めて(?:まいり|参り)ます|検討してまいりたい|検討する考え)[^。]*。')
ANS = re.compile(r'知事|部長|長君|教育長|局長|監君')
NOT = re.compile(r'議長|委員長君')
c = collections.Counter(); spk = collections.Counter()
for f in sorted(glob.glob('data/text/*.jsonl')):
    k = pathlib.Path(f).stem.rsplit('_', 1)[0]
    for l in open(f, encoding='utf-8'):
        s = json.loads(l)
        if ANS.search(s['speaker']) and not NOT.search(s['speaker']):
            n = len(PAT.findall(s['text'])); c[k] += n
            if n: spk[re.sub(r'[^\s]{2,5}君$', '', s['speaker'])] += n
for k, v in c.items(): print(k, v)
print('合計', sum(c.values()))
print(spk.most_common(12))
