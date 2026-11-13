"""会議の並び順（あとの会議ほど大きい）。"""
ORDER = {'yosan_R07-2': 1, 'yosan_R07-3': 2, 'kessan_R07': 2.5, 'yosan_R07-4': 3, 'yosan_R08-1': 4,
         'honkaigi_R08-2': 5, 'yosan_R08-2': 5, 'honkaigi_R08-3': 6}
LABEL = {'yosan_R07-2': '予算特別委 令和7年第2回', 'yosan_R07-3': '予算特別委 令和7年第3回', 'kessan_R07': '決算特別委 令和7年',
         'yosan_R07-4': '予算特別委 令和7年第4回', 'yosan_R08-1': '予算特別委 令和8年第1回', 'honkaigi_R08-2': '本会議 令和8年第2回',
         'yosan_R08-2': '予算特別委 令和8年第2回', 'honkaigi_R08-3': '本会議 令和8年第3回'}
# watch.py が見つけた新しい会議（data/sessions_extra.json）を足す
import json as _json, pathlib as _pl
_x = _pl.Path(__file__).resolve().parent.parent / 'data' / 'sessions_extra.json'
if _x.exists():
    for _k, _v in _json.load(open(_x, encoding='utf-8')).items():
        ORDER.setdefault(_k, _v['order']); LABEL.setdefault(_k, _v['label'])
def session_of(any_id):
    return any_id.split('#')[0].rsplit('_', 1)[0]
