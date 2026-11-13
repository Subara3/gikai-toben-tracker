"""SNSで共有されたときのカード画像 site_src/og.png（1200x630）を作る。
site/data.json の到達点の割合で議場の席を塗る。ヘッドレスChromeで撮る。
使い方: python scripts/make_og.py"""
import json, math, pathlib, subprocess, collections
ROOT = pathlib.Path(__file__).resolve().parent.parent
d = json.loads((ROOT / 'site' / 'data.json').read_text(encoding='utf-8'))
ORDER = ['実施・決定', '検討継続', '取組中', '見送り', '言及なし']
COL = {'実施・決定': '#1a7f37', '検討継続': '#0b5cad', '取組中': '#9a6700', '見送り': '#b42318', '言及なし': '#afb8c1'}
c = collections.Counter(i['reached'] for i in d['items']); n = len(d['items'])

pos = []
for r, k in [[40, 16], [52, 21], [64, 26], [76, 31], [88, 36], [100, 41]]:
    for j in range(k):
        a = math.pi * (j + .5) / k
        pos.append((a, 120 - r * math.cos(a), 112 - r * math.sin(a)))
pos.sort()
cols = [k for k in ORDER for _ in range(round(c[k] / n * len(pos)))]
seats = ''.join(
    f'<rect x="{x-3:.1f}" y="{y-3:.1f}" width="6" height="6" fill="{COL[cols[j] if j < len(cols) else "言及なし"]}" '
    f'transform="rotate({a*180/math.pi-90:.1f} {x:.1f} {y:.1f})"/>' for j, (a, x, y) in enumerate(pos))
acc = 0; stops = []
for k in ORDER:
    if c[k]:
        stops.append(f'{COL[k]} {acc:.2f}% {acc + c[k]/n*100:.2f}%'); acc += c[k] / n * 100
nses = len(d['meta']['sessions'])

html = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Zen+Kaku+Gothic+New:wght@500;700&display=block" rel="stylesheet">
<style>
html,body{{margin:0;width:1200px;height:630px;overflow:hidden}}
body{{background:#0f1722;color:#fff;font-family:"Zen Kaku Gothic New",sans-serif;
 background-image:linear-gradient(rgba(255,255,255,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.05) 1px,transparent 1px);background-size:40px 40px;position:relative}}
.band{{position:absolute;left:0;right:0;bottom:0;height:14px;background:linear-gradient(90deg,{",".join(stops)})}}
.l{{position:absolute;left:80px;top:96px;width:640px}}
.k{{font-size:24px;letter-spacing:.16em;color:#9fc3ea;display:flex;align-items:center;gap:14px}}
.k::before{{content:"";width:14px;height:14px;background:#9fc3ea}}
h1{{font-size:76px;font-weight:700;letter-spacing:.06em;line-height:1.2;margin:26px 0 0}}
.sub{{font-size:28px;color:#c9d3de;margin-top:22px;line-height:1.6}}
.st{{display:flex;margin-top:44px;border-top:1px solid rgba(255,255,255,.25)}}
.st div{{white-space:nowrap;padding:14px 26px 0 0;margin-right:26px;border-right:1px solid rgba(255,255,255,.16)}}
.st div:last-child{{border:0}}
.st dt{{font-size:18px;color:#9aa7b5;letter-spacing:.08em}}
.st dd{{margin:0;font-family:"DM Mono",monospace;font-size:44px;font-weight:500}}
.st small{{font-family:"Zen Kaku Gothic New";font-size:18px;color:#9aa7b5;margin-left:4px}}
svg{{position:absolute;right:56px;top:150px;width:500px}}
.url{{position:absolute;right:80px;bottom:46px;font-family:"DM Mono",monospace;font-size:22px;color:#9fc3ea;letter-spacing:.06em}}
</style></head><body>
<div class="l"><div class="k">北海道議会編</div>
<h1>議会答弁<br>トラッカー</h1>
<div class="sub">「検討してまいります」は<br>その後どうなったか</div>
<dl class="st"><div><dt>拾った約束</dt><dd>{d["meta"]["promises"]:,}<small>件</small></dd></div><div><dt>同じ件をまとめて</dt><dd>{d["meta"]["count"]:,}<small>件</small></dd></div><div><dt>読んだ会議</dt><dd>{nses}<small>回</small></dd></div></dl></div>
<svg viewBox="0 0 240 124"><path d="M8 112a112 112 0 0 1 224 0M92 112a28 28 0 0 1 56 0" fill="none" stroke="rgba(255,255,255,.16)"/>
<path d="M4 112h232" stroke="rgba(255,255,255,.4)"/>{seats}<rect x="108" y="98" width="24" height="10" fill="none" stroke="#9fc3ea" stroke-width="1.2"/></svg>
<div class="url">subara3.sakura.ne.jp</div><div class="band"></div>
</body></html>'''
tmp = ROOT / 'site' / '_og.html'
tmp.write_text(html, encoding='utf-8')
chrome = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
subprocess.run([chrome, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--window-size=1200,630',
                '--virtual-time-budget=8000', f'--screenshot={ROOT / "site_src" / "og.png"}', tmp.as_uri()], check=True)
tmp.unlink()
print('site_src/og.png')
