"""変換結果を resourceInfo_<種類>.csv として書き出す(ファイル仕様書)。

形式: UTF-8(BOMなし)、改行CRLF、全フィールドをダブルクォートで囲む、1行1リソース。
列は "objectId","data"(dataはJSON文字列。CSVとしては " を "" にエスケープする)。
"""

import json
import os

from .converters import RESOURCE_KINDS
from .errors import ToolError

HEADER = '"objectId","data"\r\n'


def file_name(kind):
    return "resourceInfo_%s.csv" % kind


def _quote(text):
    return '"' + text.replace('"', '""') + '"'


def to_csv_bytes(resources):
    """リソース(辞書)のリストを、CSVのバイト列にする。"""
    lines = [HEADER]
    for res in resources:
        data = json.dumps(res, ensure_ascii=False)
        lines.append("%s,%s\r\n" % (_quote(res["objectId"]), _quote(data)))
    return "".join(lines).encode("utf-8")


def write_outputs(result, output_dir):
    """種類ごとに順にCSVを書く。書き込みに失敗したら、書き出し済みのファイルは残す。

    各ファイルは一時ファイル(.<名前>.tmp)に書いてから置き換える。
    戻り値: 書き出したファイルのパスのリスト(RESOURCE_KINDS の順)
    """
    if os.path.exists(output_dir) and not os.path.isdir(output_dir):
        raise ToolError("出力先がディレクトリではありません: %s" % output_dir)
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as exc:
        raise ToolError("出力ディレクトリを作成できません: %s (%s)" % (output_dir, exc))

    written = []
    for kind in RESOURCE_KINDS:
        name = file_name(kind)
        path = os.path.join(output_dir, name)
        tmp = os.path.join(output_dir, "." + name + ".tmp")
        try:
            with open(tmp, "wb") as f:
                f.write(to_csv_bytes(result[kind]))
            os.replace(tmp, path)
        except OSError as exc:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            raise ToolError("出力ファイルを書き込めません: %s (%s)" % (name, exc))
        written.append(path)
    return written
