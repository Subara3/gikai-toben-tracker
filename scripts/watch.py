"""毎日1回（さくらのVPSのcron）：北海道議会サイトの会議録一覧を見て、新しい会議録PDFがあれば取り込む。
  1. 一覧ページ（本会議・予算特別委・決算特別委）と各会議のページから、PDFの一覧を取る（1秒ずつ間を空ける）
  2. まだ持っていないPDFを取得 → 本文を取り出す → 塊に分けて埋め込む（data/chunks_inc, data/emb/inc_*.npy）
  3. 判定は、その会議の新しいPDFが WAIT_DAYS 日出なくなってから、まとめて行う（data/pending_judge.json で待つ）
     - これまでの約束を差分更新で判定する（update.py。前の結果があれば、新しいPDFの塊が抜粋に入る約束だけ）
     - その会議がいちばん新しい会議なら、その会議で出た約束を拾って追跡の一覧に足す（new_promises）
     - 安全策：先にAIの回数を見積もり、1日の上限 RUN_MAX か、月の残り（上限−MARGIN）を超えるなら判定しない
  4. 判定したらサイトを作り直してレンタルサーバに上げる
新しいPDFがなくても、確認した時刻を site/status.json に書いて上げる（サイトの「最終確認」）。
使い方: python scripts/watch.py [--check-only] [--no-deploy]"""
import json, re, time, pathlib, sys, subprocess, datetime, argparse, urllib.request, glob, shutil
sys.path.insert(0, str(pathlib.Path(__file__).parent))

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = 'https://www.gikai.pref.hokkaido.lg.jp'
LISTS = {'honkaigi': '/kaigiroku/kaigiroku_sokuhou/honkaigi/', 'yosan': '/kaigiroku/kaigiroku_sokuhou/yosan/',
         'kessan': '/kaigiroku/kaigiroku_sokuhou/kessan/'}
KIND = {'honkaigi': '本会議', 'yosan': '予算特別委', 'kessan': '決算特別委'}
UA = {'User-Agent': 'Mozilla/5.0 (gikai-tsuiseki; personal research)'}
PDF = ROOT / 'data' / 'raw' / 'pdf'
MANF = PDF / 'manifest.json'
EXTRA = ROOT / 'data' / 'sessions_extra.json'
STATUS = ROOT / 'site' / 'status.json'
LOG = ROOT / 'data' / 'watch_log.jsonl'
JST = datetime.timezone(datetime.timedelta(hours=9))
PY = sys.executable
ENV = {**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}


def get(u):
    time.sleep(1)
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read()


def half(s):
    return s.translate(str.maketrans('０１２３４５６７８９', '0123456789'))


def text_of(h):
    return half(re.sub(r'<[^>]+>|\s+', ' ', h)).strip()


def discover():
    """{会議の識別名: {'page', 'title', 'pdfs': [(url, ラベル)]}}"""
    found = {}
    for kind, path in LISTS.items():
        html = get(BASE + path).decode('utf-8', 'replace')
        for href, t in re.findall(r'<a[^>]+href="(/kaigiroku/kaigiroku_sokuhou/' + kind + r'/[^"/]+\.html)"[^>]*>(.*?)</a>', html, re.S):
            t = text_of(t)
            m = re.search(r'令和(\d+)年(?:第(\d+)回)?', t)
            if not m: continue
            key = f'{kind}_R{int(m[1]):02d}' + (f'-{int(m[2])}' if m[2] else '')
            found.setdefault(key, {'page': BASE + href, 'title': t, 'kind': kind, 'yy': int(m[1]), 'n': int(m[2]) if m[2] else None})
    for v in found.values():
        html = get(v['page']).decode('utf-8', 'replace')
        v['pdfs'] = [(BASE + h, text_of(l)) for h, l in re.findall(r'<a[^>]+href="(/fs/[^"]+\.pdf)"[^>]*>(.*?)</a>', html, re.S)]
    return found


def register_session(key, v):
    """sessions.py にない会議を data/sessions_extra.json に足す。並び順は、同じ定例会の会議と同じにする"""
    from sessions import ORDER
    if key in ORDER: return
    def grp(k):
        m = re.match(r'(honkaigi|yosan|kessan)_R(\d+)(?:-(\d+))?$', k)
        return (int(m[2]), int(m[3]) if m[3] else None) if m else None
    g = (v['yy'], v['n'])
    same = [ORDER[k] for k in ORDER if grp(k) == g]
    if same: order = same[0]
    elif v['kind'] == 'kessan':  # 決算特別委は第3回定例会のあと
        third = [ORDER[k] for k in ORDER if grp(k) == (v['yy'], 3)]
        order = third[0] + 0.5 if third else max(ORDER.values()) + 1
    else: order = max(ORDER.values()) + 1
    label = f'{KIND[v["kind"]]} 令和{v["yy"]}年' + (f'第{v["n"]}回' if v['n'] else '')
    ex = json.load(open(EXTRA, encoding='utf-8')) if EXTRA.exists() else {}
    ex[key] = {'order': order, 'label': label}
    EXTRA.write_text(json.dumps(ex, ensure_ascii=False, indent=1), encoding='utf-8')
    ORDER[key] = order


def chunk_file(text_jsonl):
    """chunks.py と同じ切り方で、1つのPDFの発言を400字以内の塊にする"""
    from sessions import session_of
    out = []
    for s in map(json.loads, open(text_jsonl, encoding='utf-8')):
        if len(s['text']) < 40: continue
        ss = [x + '。' for x in s['text'].split('。') if x.strip()]
        buf, k0 = '', 0
        for k, x in enumerate(ss):
            if buf and len(buf) + len(x) > 400:
                out.append({'kid': f'{s["id"]}.{k0}', 'session': session_of(s['id']), 'speaker': s['speaker'], 'text': buf}); buf, k0 = '', k
            buf += x
        if buf: out.append({'kid': f'{s["id"]}.{k0}', 'session': session_of(s['id']), 'speaker': s['speaker'], 'text': buf})
    return out


def ingest(stem):
    """PDF 1本：本文を取り出し、塊に分けて埋め込む"""
    import numpy as np, sakura
    from extract import page_text, split_speeches
    from embed_chunks import MODEL, norm
    lines = page_text(PDF / f'{stem}.pdf')
    txt = ROOT / 'data' / 'text'
    (txt / f'{stem}.txt').write_text('\n'.join(lines), encoding='utf-8')
    with open(txt / f'{stem}.jsonl', 'w', encoding='utf-8') as f:
        for i, s in enumerate(split_speeches(lines)):
            s['id'] = f'{stem}#{i}'; f.write(json.dumps(s, ensure_ascii=False) + '\n')
    K = chunk_file(txt / f'{stem}.jsonl')
    ci = ROOT / 'data' / 'chunks_inc'; ci.mkdir(exist_ok=True)
    vec = []
    for i in range(0, len(K), 500):
        vec.append(norm(sakura.embed(MODEL, [k['text'][:400] for k in K[i:i + 500]], tag=f'embed:inc:{stem}:{i // 500}')))
    np.save(ROOT / 'data' / 'emb' / f'inc_{stem}.npy', np.concatenate(vec).astype(np.float16))
    (ci / f'{stem}.jsonl').write_text(''.join(json.dumps(k, ensure_ascii=False) + '\n' for k in K), encoding='utf-8')
    return len(K)


GEMMA = 'preview/gemma-4-31B-it'
PENDING = ROOT / 'data' / 'pending_judge.json'  # PDFは取ったが、まだ判定していない会議
WAIT_DAYS = 7    # その会議の新しいPDFがこの日数出なければ、まとめて判定する
RUN_MAX = 400    # 1日に使ってよいAIの回数（見積もりがこれを超える判定はしない）
MARGIN = 100     # 月の上限の手前に残す回数


def run(script, *args):
    return subprocess.run([PY, str(ROOT / 'scripts' / script), *args], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', env=ENV)


def newest(k):
    from sessions import ORDER
    return not any(v > ORDER[k] for v in ORDER.values())


def plan_requests(k, stems):
    """判定にかかる回数の見積もり：update.py の回数＋（いちばん新しい会議なら）約束を拾う回数"""
    r = run('update.py', k, '--new-stems', ','.join(stems), '--plan')
    n = json.loads(r.stdout.strip().splitlines()[-1])['requests'] if r.returncode == 0 else 10 ** 6
    if newest(k):
        run('candidates.py', k)  # AIを使わない
        cand = ROOT / 'data' / 'cand' / f'{k}.jsonl'
        pred = ROOT / 'data' / 'pred' / f'{k}.gemma-4-31B-it.per60.kijun2.jsonl'
        c = sum(1 for _ in open(cand, encoding='utf-8')) if cand.exists() else 0
        d = sum(1 for l in open(pred, encoding='utf-8') if json.loads(l)['label']) if pred.exists() else 0
        n += -(-max(c - d, 0) // 60) + 3  # 60文ずつの判定＋埋め込み2回＋1回の余裕
    n += 40  # 件名の付け直し（新しいカード20件で1回）と同じ件の判定（埋め込み2回＋新しい組10組で1回）の見込み
    return n


def new_promises(k):
    """いちばん新しい会議なら、その会議で出た約束を拾って追跡の一覧に足す。
    candidates.py（AIなし）→ classify.py（60文ずつ判定、済んだ文は飛ばす）→ track.py（あとの会議がないので一覧を書くだけ）"""
    if not newest(k):
        return 'あとの会議があるので拾わない'
    steps = [['candidates.py', k], ['classify.py', k, GEMMA, '--per', '60', '--suffix', '.kijun2'],
             ['track.py', k, GEMMA, '--out-suffix', '.v4']]
    msg = []
    for s in steps:
        r = run(*s)
        last = (r.stdout.strip() or r.stderr.strip()).splitlines()
        msg.append(f'{s[0]}: ' + (last[-1] if last else '') + ('' if r.returncode == 0 else ' 失敗'))
        if r.returncode: break
    return msg


def history(cur):
    """動き続けている記録：確認した日（1日1マス）。watch_log.jsonl と今回の分から作る。サイトの下に出す"""
    days = {}
    rows = [json.loads(l) for l in open(LOG, encoding='utf-8')] if LOG.exists() else []
    for r in rows + [cur]:
        d = days.setdefault(r['checked'][:10], {'n': 0, 'r': 0})
        if r.get('test'): continue  # 通しの試し（PDFを未取得扱いにして流した回）は、確認した日としてだけ数える
        d['n'] += len(r.get('new_pdfs', [])); d['r'] += r.get('requests', 0)
    ds = sorted(days)
    y, m, dd = map(int, ds[0].split('-'))
    return {'since': f'{y}年{m}月{dd}日', 'days': len(ds),
            'log': [{'d': d, **days[d]} for d in ds[-60:]]}


def notify(msg):
    """知らせ：.env に NOTIFY_WEBHOOK（DiscordのWebhook URL）があれば送る。なければ何もしない"""
    try:
        env = dict(l.strip().split('=', 1) for l in open(ROOT / '.env', encoding='utf-8') if '=' in l and not l.startswith('#'))
        url = env.get('NOTIFY_WEBHOOK', '').strip('"')
        if not url: return
        body = json.dumps({'content': f'[議会答弁トラッカー] {msg}'[:1900]}).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=body, method='POST',
                               headers={'Content-Type': 'application/json', 'User-Agent': 'gikai-tsuiseki'}), timeout=30)
    except Exception as e:
        print('知らせを送れなかった', e, file=sys.stderr)


def deploy(files):
    if 'data.json' in files:  # サイトを作り直したときは、全部（全文検索の索引も）上げる
        subprocess.run(['sh', str(ROOT / 'scripts' / 'deploy.sh')], check=True); return
    site = ROOT / 'site'
    subprocess.run(['scp', '-q', *[str(site / f) for f in files], 'sakura-rs:www/'], check=True)
    subprocess.run(['ssh', 'sakura-rs', 'chmod 644 ' + ' '.join(f'~/www/{f}' for f in files)], check=True)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--check-only', action='store_true'); ap.add_argument('--no-deploy', action='store_true')
    a = ap.parse_args()
    t0 = datetime.datetime.now(JST)
    try:
        import sakura; used = sakura.used_this_month
    except (FileNotFoundError, KeyError):  # トークン（.env）がまだないときは、確認だけする
        sakura, used = None, lambda: 0; a.check_only = True
    used0 = used()
    man = json.load(open(MANF, encoding='utf-8'))
    have = {m['url'] for m in man}
    found = discover()
    new = [(k, v, u, l) for k, v in found.items() for u, l in v['pdfs'] if u not in have]
    log = {'checked': t0.isoformat(timespec='seconds'), 'sessions': len(found), 'pdfs': sum(len(v['pdfs']) for v in found.values()),
           'new_pdfs': [f'{k} {l}' for k, _, _, l in new]}
    changed = sorted({k for k, *_ in new})
    pend = json.load(open(PENDING, encoding='utf-8')) if PENDING.exists() else {}
    if new and not a.check_only:
        # 取得・本文・埋め込みは毎日。判定は、その会議の新しいPDFが WAIT_DAYS 日出なくなってからまとめて行う
        for k in changed: register_session(k, found[k])
        for k, v, u, l in new:
            n = 1 + max([int(m['file'].rsplit('_', 1)[1][:2]) for m in man if m['session'] == k] or [0])
            name = f'{k}_{n:02d}.pdf'
            (PDF / name).write_bytes(get(u))
            man.append({'file': name, 'session': k, 'label': l, 'url': u, 'page': v['page']})
            MANF.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding='utf-8')
            log.setdefault('chunks', {})[name] = ingest(name[:-4])
            p = pend.setdefault(k, {'stems': []}); p['stems'].append(name[:-4]); p['last_new'] = t0.date().isoformat()
            PENDING.write_text(json.dumps(pend, ensure_ascii=False, indent=1), encoding='utf-8')
    built = False
    if pend and not a.check_only:
        from sessions import ORDER
        for k in sorted(pend, key=lambda x: (ORDER.get(x, 0), x)):
            p = pend[k]
            if (t0.date() - datetime.date.fromisoformat(p['last_new'])).days < WAIT_DAYS:
                log.setdefault('waiting', {})[k] = f'{p["last_new"]} にPDFが出たので待つ'; continue
            need = plan_requests(k, p['stems'])
            room = min(RUN_MAX - (used() - used0), sakura.remaining() - MARGIN)
            if need > room:  # 安全策：多すぎるときは判定しない。翌日また見積もる（watch_log に残る）
                log.setdefault('held', {})[k] = f'見積もり {need} 回が、今日使える {room} 回を超えるので止めた'; continue
            inc = ROOT / 'data' / 'track_inc' / f'{k}.jsonl'
            if inc.exists(): shutil.copy(inc, inc.with_suffix(f'.{t0:%Y%m%d%H%M}.bak'))  # 前の結果の控え
            # 前の結果があれば、新しいPDFの塊が抜粋に入る約束だけを判定し直す
            r = run('update.py', k, '--new-stems', ','.join(p['stems']))
            log.setdefault('update', {})[k] = (r.stderr.strip().splitlines() or [''])[0] + ('' if r.returncode == 0 else ' 失敗')
            log.setdefault('promises', {})[k] = new_promises(k)
            del pend[k]; PENDING.write_text(json.dumps(pend, ensure_ascii=False, indent=1), encoding='utf-8')
            built = True
    if built:
        r = run('build_site.py')
        # 新しいカードの件名をAIで付け直し（済んだものは飛ばす）、同じ件の判定をして（済んだ組は飛ばす）、作り直す
        log['subjects'] = (run('fix_subjects.py').stderr.strip().splitlines() or [''])[0]
        log['merge'] = (run('merge_ai.py').stdout.strip().splitlines() or [''])[-1]
        r = run('build_site.py')
        log['build'] = r.stdout.strip() or r.stderr.strip()[-200:]
        r = run('build_search.py')  # 全文検索の索引（AIなし）
        log['search'] = r.stdout.strip() or r.stderr.strip()[-200:]
    log['requests'] = used() - used0
    prev = json.load(open(STATUS, encoding='utf-8')) if STATUS.exists() else {}
    STATUS.write_text(json.dumps({
        'checked': f'{t0.year}年{t0.month}月{t0.day}日 {t0:%H:%M}',
        'last_new': (f'{t0.year}年{t0.month}月{t0.day}日' if new and not a.check_only else prev.get('last_new', '')),
        'sessions': len(found), 'pdfs': log['pdfs'], **history(log)}, ensure_ascii=False), encoding='utf-8')
    if not a.no_deploy:
        deploy(['status.json', 'index.html', 'data.json'] if built else ['status.json'])
        log['deployed'] = True
    with open(LOG, 'a', encoding='utf-8') as f: f.write(json.dumps(log, ensure_ascii=False) + '\n')
    print(json.dumps(log, ensure_ascii=False))
    if log['new_pdfs']: notify(f'新しい会議録PDF {len(log["new_pdfs"])}本：' + '、'.join(log['new_pdfs'])[:600])
    if log.get('held'): notify('判定を止めた：' + json.dumps(log['held'], ensure_ascii=False))
    if built: notify(f'判定してサイトを更新した（AI {log["requests"]}回）：' + json.dumps(log.get('update', {}), ensure_ascii=False)[:600])


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        notify(f'毎日の確認が失敗した：{type(e).__name__}: {str(e)[:300]}')
        raise
