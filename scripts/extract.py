"""会議録PDF（一太郎製）から本文を取り出し、発言ごとに区切ってJSONLにする。
pdftotext は Windows で日本語が抜けるので pymupdf を使う。"""
import sys, re, json, pathlib
import fitz

SPEAKER = re.compile(r'^○(?P<who>[^（\s]+?君|[^（\s]+?)(?:（登壇）)?(?=[　\s]|（)')

def page_text(path):
    d = fitz.open(path)
    lines = []
    for p in d:
        for ln in p.get_text().splitlines():
            ln = ln.rstrip()
            if ln.strip(): lines.append(ln)
    return lines

TITLE = r'(?:副委員長|委員長|委員|副知事|知事|教育長|本部長|副議長|議長|課長|部長|局長|室長|次長|参事|監|事務局長|委員長君)'
HEAD = re.compile(r'【[^】]{0,40}第[０-９\d]+号】|^.*令和\d+年.*第[０-９\d]+号.*$')
NAME = re.compile(r'○(.{1,24}?君|.{1,24}?' + TITLE + r')(?:（登壇）)?')

def split_speeches(lines):
    out, cur = [], None
    for ln in lines:
        s = HEAD.sub('', ln.strip())
        if not s:
            continue
        if s.startswith('○'):
            if cur: out.append(cur)
            m = NAME.match(s)
            who = m.group(1) if m else s[1:15]
            body = s[m.end():] if m else s
            cur = {'speaker': who, 'text': body}
        elif cur is not None:
            cur['text'] += s
    if cur: out.append(cur)
    return out

if __name__ == '__main__':
    src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    dst.mkdir(parents=True, exist_ok=True)
    for pdf in sorted(src.glob('*.pdf')):
        lines = page_text(pdf)
        (dst / (pdf.stem + '.txt')).write_text('\n'.join(lines), encoding='utf-8')
        sp = split_speeches(lines)
        with open(dst / (pdf.stem + '.jsonl'), 'w', encoding='utf-8') as f:
            for i, s in enumerate(sp):
                s['id'] = f'{pdf.stem}#{i}'
                f.write(json.dumps(s, ensure_ascii=False) + '\n')
        print(pdf.stem, len(lines), 'lines', len(sp), 'speeches', sum(len(s['text']) for s in sp), 'chars')
