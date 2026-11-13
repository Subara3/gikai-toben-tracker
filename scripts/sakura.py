"""さくらのAI Engine 呼び出し（OpenAI互換）。リクエストは1回ごとに data/ledger.jsonl に記録し、
月の上限を超えたら止める。既定1,500：手元のPCとVPSが同じトークン（無償プラン、チャット・埋め込みそれぞれ月3,000回）を使うので、
両方が上限まで使っても合計3,000回に届かないようにする。
リトライは自前で1回だけ。"""
import json, os, time, urllib.request, urllib.error, pathlib, datetime
ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV = dict(l.strip().split('=', 1) for l in open(ROOT / '.env', encoding='utf-8') if '=' in l and not l.startswith('#'))
TOKEN = ENV['SAKURA_AI_TOKEN'].strip('"')
BASE = 'https://api.ai.sakura.ad.jp/v1'
LEDGER = ROOT / 'data' / 'ledger.jsonl'
MONTH_CAP = int(os.environ.get('SAKURA_MONTH_CAP', '1500'))

def used_this_month():
    if not LEDGER.exists(): return 0
    m = datetime.date.today().strftime('%Y-%m')
    return sum(1 for l in open(LEDGER, encoding='utf-8') if json.loads(l)['ts'].startswith(m))

def remaining():
    return MONTH_CAP - used_this_month()

def _post(path, body, tag):
    if used_this_month() >= MONTH_CAP:
        raise RuntimeError(f'今月の上限 {MONTH_CAP} 回に達した')
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method='POST',
        headers={'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json'})
    t0 = time.time(); status = None
    try:
        r = urllib.request.urlopen(req, timeout=600); status = r.status; d = json.load(r)
        return d
    except urllib.error.HTTPError as e:
        status = e.code; raise RuntimeError(f'HTTP {e.code}: {e.read()[:300]!r}')
    finally:
        LEDGER.parent.mkdir(exist_ok=True)
        with open(LEDGER, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'ts': datetime.datetime.now().isoformat(timespec='seconds'), 'path': path,
                'model': body.get('model'), 'tag': tag, 'status': status, 'sec': round(time.time() - t0, 1)}, ensure_ascii=False) + '\n')

def chat(model, messages, tag='', schema=None, **kw):
    body = {'model': model, 'messages': messages, **kw}
    if schema:
        body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'out', 'schema': schema, 'strict': True}}
    for attempt in (0, 1):
        try:
            d = _post('/chat/completions', body, tag)
            return d['choices'][0]['message']['content'], d.get('usage', {})
        except RuntimeError as e:
            if attempt or 'HTTP 4' in str(e): raise
            time.sleep(5)

def embed(model, inputs, tag=''):
    d = _post('/embeddings', {'model': model, 'input': inputs}, tag)
    return [x['embedding'] for x in d['data']]
