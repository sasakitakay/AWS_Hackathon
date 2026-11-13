"""入力CSV(ノード/エンティティ/サービス)の選択と読み込み。"""

import csv
import io
import os
import re

from .errors import ToolError

# 入力ファイルの種類。ファイル名の接頭辞 -> 種類名
FILE_PREFIXES = (
    ("t_mst_vxm_node_info_", "node"),
    ("t_mst_vxm_entity_info_", "entity"),
    ("t_mst_vxm_service_", "service"),
)
_FILE_RE = re.compile(r"^(t_mst_vxm_node_info|t_mst_vxm_entity_info|t_mst_vxm_service)_(\d{12})\.csv$")
_PREFIX_TO_KIND = {
    "t_mst_vxm_node_info": "node",
    "t_mst_vxm_entity_info": "entity",
    "t_mst_vxm_service": "service",
}

# 列名(入力CSVの列順どおり)
NODE_COLUMNS = [
    "ra_vxm_id", "ra_job_id", "ra_updated_at", "ra_created_at", "name", "node_type",
    "parent_node_group_id", "parent_node_group_name", "parent_node_id", "parent_node_name",
    "product_name", "product_version", "description", "vendor_name", "protocol",
    "node_profile_id", "node_profile_name", "username", "password", "connection_type",
    "primary_port", "secondary_port", "external_id", "plug_in", "telemetry_username",
    "telemetry_password", "telemetry_port", "scope_id_list", "scope_name_list",
    "requests_per_time_period", "admin_status", "latitude", "longitude", "address",
    "location", "memo", "oper_status", "timezone", "last_alarm_sync_at",
    "primary_ipv4_address", "primary_ipv6_address", "secondary_ipv4_address",
    "secondary_ipv6_address", "unification_bldg_code", "build_name", "area_name",
    "prefecture", "floor_rack", "host_name", "neops_number", "neops_serial_number",
    "neops_traffic_url", "neops_top_url", "controller_vip_address", "neops_ip_address",
    "node_template", "application_monitor_template", "simple_control_template",
]
ENTITY_COLUMNS = [
    "ra_vxm_id", "ra_job_id", "ra_updated_at", "ra_created_at", "name", "description", "memo",
    "node_name", "node_id", "entity_profile_name", "entity_profile_id", "parent_entity_name",
    "parent_entity_id", "type", "mac_address", "ipv4_address", "ipv6_address", "admin_status",
    "oper_status", "mtu", "speed", "link_id", "link_name", "service_id", "service_name",
    "scope_id_list", "scope_name_list", "external_id", "snmp_oid", "snmp_index", "snmp_type",
    "snmp_type_id", "created_by",
]
SERVICE_COLUMNS = [
    "ra_vxm_id", "ra_job_id", "ra_updated_at", "ra_created_at", "name", "description", "memo",
    "service_profile_id", "service_profile_name", "admin_status", "oper_status",
    "protection_status", "external_id", "network_entity_id_list", "network_entity_name_list",
    "client_entity_id_list", "client_entity_name_list", "network_service_id_list",
    "network_service_name_list", "network_protection_service_id_list",
    "network_protection_service_name_list", "severity", "priority", "type", "protection_type",
    "service_status",
]

COLUMNS = {"node": NODE_COLUMNS, "entity": ENTITY_COLUMNS, "service": SERVICE_COLUMNS}
# 配列として扱う列(列名が _list で終わるもの)
LIST_COLUMNS = {
    kind: frozenset(c for c in cols if c.endswith("_list")) for kind, cols in COLUMNS.items()
}


class Row(dict):
    """入力CSVの1行。列名 -> 値(配列列は文字列のリスト)。line は元ファイルの行番号。"""

    line = 0


def parse_pg_array(text):
    """PostgreSQL配列表記('{a,b}'、'{"x y","z"}')を文字列のリストにする。空文字は空リスト。

    形式が不正なら ValueError を送出する。
    """
    s = text.strip()
    if s == "":
        return []
    if len(s) < 2 or s[0] != "{" or s[-1] != "}":
        raise ValueError("配列表記ではありません: %r" % text)
    body = s[1:-1]
    items = []
    i = 0
    n = len(body)
    if n == 0:
        return items
    while True:
        if i < n and body[i] == '"':
            i += 1
            buf = []
            while True:
                if i >= n:
                    raise ValueError("引用符が閉じられていません: %r" % text)
                ch = body[i]
                if ch == "\\":
                    if i + 1 >= n:
                        raise ValueError("エスケープが途中で終わっています: %r" % text)
                    buf.append(body[i + 1])
                    i += 2
                elif ch == '"':
                    i += 1
                    break
                else:
                    buf.append(ch)
                    i += 1
            items.append("".join(buf))
        else:
            j = i
            while j < n and body[j] != ",":
                j += 1
            items.append(body[i:j].strip())
            i = j
        if i >= n:
            break
        if body[i] != ",":
            raise ValueError("区切りが不正です: %r" % text)
        i += 1
        if i >= n:
            raise ValueError("末尾の要素がありません: %r" % text)
    return items


def select_input_files(input_dir):
    """入力ディレクトリ直下から、種類ごとに最新時刻のファイルを選ぶ。

    戻り値: {"node": パス, "entity": パス, "service": パス}
    3種のどれにも当てはまらないファイルがある、または種類がそろわない場合は ToolError。
    """
    if not os.path.exists(input_dir):
        raise ToolError("入力ディレクトリが存在しません: %s" % input_dir)
    if not os.path.isdir(input_dir):
        raise ToolError("入力ディレクトリがディレクトリではありません: %s" % input_dir)
    try:
        names = sorted(os.listdir(input_dir))
    except OSError as exc:
        raise ToolError("入力ディレクトリの読み込みに失敗しました: %s (%s)" % (input_dir, exc))

    latest = {}  # 種類 -> (時刻, ファイル名)
    for name in names:
        if not os.path.isfile(os.path.join(input_dir, name)):
            continue  # サブディレクトリは対象外
        m = _FILE_RE.match(name)
        if not m:
            raise ToolError(
                "入力ディレクトリに、ノード/エンティティ/サービスのどれにも当てはまらないファイルがあります: %s" % name)
        kind = _PREFIX_TO_KIND[m.group(1)]
        stamp = m.group(2)
        if kind not in latest or stamp > latest[kind][0]:
            latest[kind] = (stamp, name)

    missing = [k for _p, k in FILE_PREFIXES if k not in latest]
    if missing:
        raise ToolError("入力ディレクトリに次の種類のファイルがありません: %s (%s)" % (", ".join(missing), input_dir))
    return {kind: os.path.join(input_dir, latest[kind][1]) for kind in COLUMNS}


def read_rows(path, kind):
    """入力CSVを読み、Row のリストを返す(BOMは取り除く)。"""
    name = os.path.basename(path)
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as exc:
        raise ToolError("入力ファイルの読み込みに失敗しました: %s (%s)" % (name, exc))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ToolError("入力ファイルをUTF-8として読めません: %s (%s)" % (name, exc))

    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader, None)
    except csv.Error as exc:
        raise ToolError("入力ファイルのCSV形式が不正です: %s (%s)" % (name, exc))
    if header is None:
        raise ToolError("入力ファイルが空です: %s" % name)
    missing = [c for c in COLUMNS[kind] if c not in header]
    if missing:
        raise ToolError("入力ファイルに必須の列がありません: %s (列: %s)" % (name, ", ".join(missing)))
    index = {c: header.index(c) for c in COLUMNS[kind]}
    list_cols = LIST_COLUMNS[kind]

    rows = []
    try:
        for fields in reader:
            if not fields:
                continue  # 空行
            line = reader.line_num
            if len(fields) != len(header):
                raise ToolError("入力ファイルの列数がヘッダと一致しません: %s (行 %d)" % (name, line))
            row = Row()
            row.line = line
            for col in COLUMNS[kind]:
                value = fields[index[col]]
                if col in list_cols:
                    try:
                        value = parse_pg_array(value)
                    except ValueError as exc:
                        raise ToolError("配列の値を読めません: %s (行 %d, 項目 %s): %s" % (name, line, col, exc))
                row[col] = value
            rows.append(row)
    except csv.Error as exc:
        raise ToolError("入力ファイルのCSV形式が不正です: %s (行 %d: %s)" % (name, reader.line_num, exc))
    return rows


def load_inputs(input_dir):
    """入力ディレクトリから (ノード, エンティティ, サービス) の Row リストを読む。"""
    files = select_input_files(input_dir)
    return (
        read_rows(files["node"], "node"),
        read_rows(files["entity"], "entity"),
        read_rows(files["service"], "service"),
    )
