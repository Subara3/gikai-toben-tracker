# 議会答弁トラッカー（北海道議会編）

北海道議会で知事や部長が「検討してまいります」と答えた件が、そのあとの会議でどうなったかを、会議録の原文とあわせて並べるサイトのコードです。

- サイト：https://subara3.sakura.ne.jp/
- 全文検索：https://subara3.sakura.ne.jp/search.html

会議録を読むところは[さくらのAI Engine](https://www.sakura.ad.jp/aipf/ai-engine/)（無償枠、月3,000リクエスト）、公開はさくらのレンタルサーバ、毎朝の更新はさくらのVPSで動かしています。

AIが読み取った結果なので、外れることがあります。確実な内容は、サイトの各件に付けた会議録PDFのリンクから原文を見てください。

## しくみ

1. 会議録PDFを取得して、発言ごとに区切る（`fetch_official.py`、`extract.py`）
2. 答弁から「これからやる」と言っている文をコードで拾う（`candidates.py`）
3. 拾った文が「検討の約束」かをAIが判定する（`classify.py`。文は番号で渡し、番号とラベルだけ返させる）
4. 全部の発言を400字以内の塊にして埋め込む（`chunks.py`、`embed_chunks.py`）
5. 約束ごとに、あとの会議から近い発言を拾い、どうなったかをAIが判定する（`track.py`）。引用は原文と照らし合わせ、合わなければ採らない
6. 件名を付け直し、同じ件をまとめる（`fix_subjects.py`、`merge_ai.py`）
7. 静的なサイトと全文検索の索引を作る（`build_site.py`、`build_search.py`）

新しい会議録が出たときは、`watch.py`が見つけて、その会議の分だけを判定します（`update.py`）。

状態は5つです：実施・決定／取組中／検討継続／見送り／言及なし。

## 入っているもの

| 場所 | 中身 |
|---|---|
| `scripts/` | 上の処理のスクリプト。`sakura.py`がAI Engineの呼び出しで、リクエストを1回ごとに台帳に書き、月の上限で止まります |
| `site_src/` | サイトの画面（一覧と全文検索） |
| `notes/判定基準.md` | 何を「約束」と呼ぶかの基準 |
| `data/gold/` | 約束の文を選ぶところの正解集（令和7年第2回 予算特別委員会、734文） |
| `data/gold_track/` | 追跡の正解集（調整用30件、検証用20件） |
| `data/overrides.json` | 手で直したもの（別の件として切り離した組、判定基準に合わず外した約束と理由） |

会議録のPDF、取り出した本文、AIの判定結果、埋め込みは入れていません。会議録は`fetch_official.py`で議会のサイトから取得します。

## 動かし方

Python 3.12で動かしています。

```sh
pip install -r requirements.txt
cp .env.example .env   # SAKURA_AI_TOKEN を入れる
```

```sh
python scripts/fetch_official.py data/raw/pdf   # 会議録PDFを取得（1秒ずつ間を空けます）
python scripts/extract.py data/raw/pdf data/text   # 発言ごとに区切る
python scripts/candidates.py yosan_R07-2    # 候補の文を拾う（AIなし）
python scripts/classify.py yosan_R07-2 preview/gemma-4-31B-it --per 60 --suffix .kijun2
python scripts/chunks.py
python scripts/embed_chunks.py
python scripts/track.py yosan_R07-2 preview/gemma-4-31B-it --out-suffix .v4
python scripts/fix_subjects.py
python scripts/merge_ai.py
python scripts/build_site.py
python scripts/build_search.py
```

毎朝の処理（cron）：

```
17 6 * * * cd ~/gikai-tsuiseki && ~/venv/bin/python scripts/watch.py >> ~/logs/watch.log 2>&1
```

AIを呼ぶスクリプトは、`data/ledger.jsonl`に回数を書きます。月の上限は環境変数`SAKURA_MONTH_CAP`（既定1,500）です。

## 精度

調整に使っていない20件（約束×あとの会議で80か所）で測った数字です。

| 項目 | 結果 |
|---|---|
| 会議ごとの状態が正解と一致した割合 | 82% |
| 「進展あり」と出したもののうち、正しかった割合 | 97% |
| 実際に進展があったもののうち、拾えた割合 | 74% |

正解集は、判定に使っていない別のAI（Claude）が会議録の原文を読んで付け、80か所を原文と照らして見直したものです。

## 出典とライセンス

- コード：MIT License（`LICENSE`）
- 会議録：[北海道議会ウェブサイト](https://www.gikai.pref.hokkaido.lg.jp/)の会議録（速報版）。サイトポリシーでCC BYとされています。`data/`の正解集には、会議録からの引用が含まれます
- 会議録検索システム（正式版）は、本文のページがrobots.txtで禁止されているので使っていません

サイトでは道政の良し悪しの評価は付けず、会議録に書いてあることを並べています。
