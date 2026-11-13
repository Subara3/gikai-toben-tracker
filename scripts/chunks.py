"""全発言を、文の途中で切らずに400字以内の塊に詰める（質問も答弁も）。追跡の検索対象。→ data/chunks.jsonl
400字を超える1文は、その文だけで1塊にする（埋め込みの入力上限のため末尾を切る）。"""
import json, glob, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from sessions import session_of
ROOT = pathlib.Path(__file__).resolve().parent.parent
LIM = 400
n = 0
with open(ROOT / 'data' / 'chunks.jsonl', 'w', encoding='utf-8') as f:
    def put(sid, spk, k, t):
        global n
        f.write(json.dumps({'kid': f'{sid}.{k}', 'session': session_of(sid), 'speaker': spk, 'text': t}, ensure_ascii=False) + '\n'); n += 1
    for p in sorted(glob.glob(str(ROOT / 'data' / 'text' / '*.jsonl'))):
        for s in map(json.loads, open(p, encoding='utf-8')):
            if len(s['text']) < 40: continue
            ss = [x + '。' for x in s['text'].split('。') if x.strip()]
            buf, k0 = '', 0
            for k, x in enumerate(ss):
                if buf and len(buf) + len(x) > LIM:
                    put(s['id'], s['speaker'], k0, buf); buf, k0 = '', k
                buf += x
            if buf: put(s['id'], s['speaker'], k0, buf)
print('塊', n)
