"""塊を埋め込む（Qwen3-Embedding、先頭1024次元に切り詰めて正規化）。途中から再開できる。
使い方: python scripts/embed_chunks.py [--batch 500] [--limit N]"""
import json, pathlib, sys, argparse, numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import sakura
ROOT = pathlib.Path(__file__).resolve().parent.parent
MODEL = 'preview/Qwen3-Embedding-4B-FP16'; DIM = 1024
def norm(v):
    v = np.asarray(v, dtype=np.float32)[:, :DIM]; return v / np.linalg.norm(v, axis=1, keepdims=True)
if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--batch', type=int, default=500); ap.add_argument('--limit', type=int, default=0); a = ap.parse_args()
    K = [json.loads(l) for l in open(ROOT / 'data' / 'chunks.jsonl', encoding='utf-8')]
    out = ROOT / 'data' / 'emb'; out.mkdir(exist_ok=True)
    nb = (len(K) + a.batch - 1) // a.batch
    for b in range(nb if not a.limit else min(nb, a.limit)):
        p = out / f'chunks_{a.batch}_{b:04d}.npy'
        if p.exists(): continue
        part = K[b * a.batch:(b + 1) * a.batch]
        vec = sakura.embed(MODEL, [k['text'][:400] for k in part], tag=f'embed:chunks:{b}')
        np.save(p, norm(vec).astype(np.float16)); print(b, len(part), file=sys.stderr)
