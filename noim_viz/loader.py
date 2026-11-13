"""出力CSV(resourceInfo_*.csv)とアラームJSONの読み込み(FR1)。"""

import csv
import json
import os

from noim.output_csv import file_name

from .errors import VizError

# 可視化で読む出力CSVの種類(装置、ポート、物理接続、論理接続)
KINDS = ("pds", "pPorts", "pls", "fres")

ALARM_FIELDS = ("alarmId", "alarmName", "alarmLevel", "targetDeviceId", "occurredAt", "status")
ALARM_STATUSES = ("active", "recovered")

# dataの1フィールドが既定の上限(131072)を超えることがあるため引き上げる
csv.field_size_limit(2 ** 31 - 1)


def load_resources(noim_dir, kind):
    """resourceInfo_<kind>.csv を読み、data(辞書)のリストを返す。objectId が無ければ data から補う。"""
    name = file_name(kind)
    path = os.path.join(noim_dir, name)
    if not os.path.isfile(path):
        raise VizError("NOIM出力ファイルが見つかりません: %s (%s)" % (name, noim_dir))
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or "objectId" not in reader.fieldnames \
                    or "data" not in reader.fieldnames:
                raise VizError("%s: ヘッダに objectId と data の列が必要です" % name)
            resources = []
            for line_no, row in enumerate(reader, start=2):
                try:
                    data = json.loads(row["data"])
                except (TypeError, ValueError) as exc:
                    raise VizError("%s: %d行目の data がJSONとして読めません (%s)" % (name, line_no, exc))
                if not isinstance(data, dict):
                    raise VizError("%s: %d行目の data がJSONオブジェクトではありません" % (name, line_no))
                if not data.get("objectId"):
                    data["objectId"] = row["objectId"]
                resources.append(data)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise VizError("NOIM出力ファイルを読めません: %s (%s)" % (name, exc))
    return resources


def load_noim(noim_dir):
    """4種のCSVを読み、{種類: [data, ...]} を返す。"""
    if not os.path.isdir(noim_dir):
        raise VizError("NOIM出力ディレクトリが存在しないか、ディレクトリではありません: %s" % noim_dir)
    return dict((kind, load_resources(noim_dir, kind)) for kind in KINDS)


def load_alarms(path):
    """アラームJSONを読んで検証し、アラーム(辞書)のリストを返す。"""
    label = os.path.basename(path)
    if not os.path.isfile(path):
        raise VizError("アラームファイルが見つかりません: %s" % path)
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            doc = json.load(f)
    except (OSError, UnicodeDecodeError) as exc:
        raise VizError("アラームファイルを読めません: %s (%s)" % (label, exc))
    except ValueError as exc:
        raise VizError("アラームファイルがJSONとして読めません: %s (%s)" % (label, exc))
    if not isinstance(doc, dict) or not isinstance(doc.get("alarms"), list):
        raise VizError("%s: ルートに alarms 配列が必要です" % label)

    alarms = []
    seen = set()
    for i, item in enumerate(doc["alarms"], start=1):
        where = "%s: alarms[%d]" % (label, i)
        if not isinstance(item, dict):
            raise VizError("%s がオブジェクトではありません" % where)
        for key in ALARM_FIELDS:
            if key not in item:
                raise VizError("%s に必須項目 %s がありません" % (where, key))
        for key in ("alarmId", "alarmName", "targetDeviceId", "occurredAt"):
            if not isinstance(item[key], str) or item[key] == "":
                raise VizError("%s の %s は空でない文字列にしてください" % (where, key))
        level = item["alarmLevel"]
        if isinstance(level, bool) or not isinstance(level, int) or level not in (1, 2, 3):
            raise VizError("%s の alarmLevel は 1〜3 の整数にしてください (値: %r)" % (where, level))
        if item["status"] not in ALARM_STATUSES:
            raise VizError("%s の status は active か recovered にしてください (値: %r)" % (where, item["status"]))
        if item["alarmId"] in seen:
            raise VizError("%s の alarmId が重複しています: %s" % (where, item["alarmId"]))
        seen.add(item["alarmId"])
        alarms.append(dict((key, item[key]) for key in ALARM_FIELDS))
    return alarms
