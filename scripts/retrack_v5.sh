#!/bin/bash
# 2026-12-01 に1回だけ：付け直した件名（data/subject_ai.json）で全会議の約束を追跡し直し、サイトを差し替える。
# 済んだら data/retrack_v5.done を作り、2回目以降は何もしない。結果の採点は data/retrack_v5.log
cd /home/gikai/gikai-tsuiseki || exit 1
P=/home/gikai/venv/bin/python
LOG=data/retrack_v5.log
[ -f data/retrack_v5.done ] && exit 0
notify() { $P -c "import sys;sys.path.insert(0,'scripts');import watch;watch.notify(sys.argv[1])" "$1"; }
REM=$($P -c "import sys;sys.path.insert(0,'scripts');import sakura;print(sakura.remaining())")
if [ "$REM" -lt 1150 ]; then echo "$(date) 残り${REM}回で足りないので止めた" >> $LOG; notify "全件の追跡し直しを止めた（今月の残り${REM}回）"; exit 0; fi
echo "$(date) 開始 残り${REM}回" >> $LOG
for s in yosan_R07-2 yosan_R07-3 kessan_R07 yosan_R07-4 yosan_R08-1 honkaigi_R08-2 yosan_R08-2 honkaigi_R08-3; do
  $P scripts/track.py $s preview/gemma-4-31B-it --out-suffix .v5 --subjects data/subject_ai.json >> $LOG 2>&1 || { notify "全件の追跡し直しが $s で失敗した"; exit 1; }
  echo "$(date) $s 済み $(wc -l < data/track/$s.gemma-4-31B-it.v5.jsonl)行" >> $LOG
done
# 数の確認：v4 と同じ行数でなければ差し替えない
for f in data/track/*.gemma-4-31B-it.v4.jsonl; do
  g=${f%.v4.jsonl}.v5.jsonl
  [ "$(wc -l < $f)" = "$(wc -l < $g)" ] || { notify "行数が合わないので差し替えない：$g"; exit 1; }
done
echo "=== 採点（検証用20件）" >> $LOG
$P scripts/score_track.py data/gold_track/R07-4.holdout.checked.jsonl data/track/yosan_R07-4.gemma-4-31B-it.v5.jsonl >> $LOG 2>&1
mkdir -p data/track_v4_backup
for f in data/track/*.gemma-4-31B-it.v4.jsonl; do cp $f data/track_v4_backup/; mv ${f%.v4.jsonl}.v5.jsonl $f; done
$P scripts/build_site.py >> $LOG 2>&1 && $P scripts/build_search.py >> $LOG 2>&1 && sh scripts/deploy.sh >> $LOG 2>&1
touch data/retrack_v5.done
notify "全件の追跡し直しが済んでサイトを更新した。$(grep 'マスの一致率\|再現率' $LOG | tail -2 | tr '\n' ' ')"
echo "$(date) 済み" >> $LOG
