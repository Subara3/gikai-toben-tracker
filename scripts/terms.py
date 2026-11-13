"""「何を」の中心の語を、漢字・カタカナ・英数の並びから2文字ずつ取り出し、塊との重なりを測る。"""
import re
GENERIC = set('検討 在り り方 取組 推進 対応 見直 直し 必要 効果 果的 今後 具体 体的 様々 取り まと 方針 施策 対策 実施 充実 強化 確保 向上 促進 支援 体制 整備 活用 連携 検証 点検 新た 本道 道内 全体 効率 率的 関係 状況 内容 計画 事業 取扱 扱い 方策 課題 向け 考え 基本 本的 今年 年度 次期 一層'.split())
RUN = re.compile(r'[一-龥々ァ-ヴーA-Za-z0-9０-９Ａ-Ｚ]{2,}')
def bigrams(subject):
    out = []
    for r in RUN.findall(subject):
        for i in range(len(r) - 1):
            b = r[i:i + 2]
            if b not in GENERIC and b not in out: out.append(b)
    return out
def overlap(subject, text):
    bs = bigrams(subject)
    return (sum(b in text for b in bs) / len(bs)) if bs else 1.0
