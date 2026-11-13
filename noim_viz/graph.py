"""装置・辺の組み立て、アラームの結びつけ、警告、サマリ(FR2、FR3、FR5.1)。

HTMLに入れる項目は許可リスト方式。ここで作る辞書にある項目だけが出力に出る
(nttManagementInfo の password などは読み取り対象外で、結果に入らない)。
"""

from .errors import VizError

PHYSICAL = "physical"
LSP = "lsp"
KIND_LABEL = {PHYSICAL: "物理接続", LSP: "LSP接続"}
MAX_NAMES_IN_WARNING = 5


def _info(data):
    info = data.get("nttManagementInfo")
    return info if isinstance(info, dict) else {}


def build_devices(pds):
    """PD から装置を作る。id=nodeRaVxmId、name=commonName、type=nodeNodeType。"""
    devices = []
    by_id = {}
    by_name = {}
    for pd in pds:
        info = _info(pd)
        dev_id = info.get("nodeRaVxmId")
        name = pd.get("commonName")
        if not dev_id or not name:
            raise VizError("装置(PD)に nodeRaVxmId または commonName がありません: %s" % pd.get("objectId"))
        if dev_id in by_id:
            raise VizError("装置のIDが重複しています: %s" % dev_id)
        if name in by_name:
            raise VizError("装置名が重複しています(アラームとの結びつけが曖昧になるため処理できません): %s" % name)
        dev = {"id": dev_id, "name": name, "type": info.get("nodeNodeType") or "",
               "alarms": [], "severity": 0}
        devices.append(dev)
        by_id[dev_id] = dev
        by_name[name] = dev
    return devices, by_id, by_name


def _port_devices(refs, port_by_oid, by_id):
    """ポートのobjectId列から、(着いた装置のidのリスト(重複なし、順序保持), 着かなかったポートの数)。"""
    ids = []
    missing = 0
    for ref in refs:
        port = port_by_oid.get(ref)
        dev_id = _info(port).get("entityNodeId") if port else None
        if dev_id in by_id:
            if dev_id not in ids:
                ids.append(dev_id)
        else:
            missing += 1
    return ids, missing


def _classify(dev_ids, missing, total):
    """端点の結果から、描けない理由(描けるなら None)を返す。"""
    if total == 0:
        return "端点がありません"
    if missing:
        return "端が装置に着きません"
    if len(dev_ids) != 2:
        return "異なる2つの装置になりません"
    return None


def build_edges(noim, by_id):
    """物理接続(PLink)とLSP接続(FRE NC)の辺を作る。戻り値: (辺のリスト, 警告のリスト)。"""
    port_by_oid = dict((p.get("objectId"), p) for p in noim["pPorts"])
    fre_by_oid = dict((f.get("objectId"), f) for f in noim["fres"])

    edges = {}
    order = []
    skipped = {}  # (kind, 理由) -> [接続名, ...]

    def add(kind, dev_ids, name):
        key = (kind,) + tuple(sorted(dev_ids))
        if key not in edges:
            edges[key] = {"source": sorted(dev_ids)[0], "target": sorted(dev_ids)[1], "kind": kind,
                          "count": 0, "names": []}
            order.append(key)
        edges[key]["count"] += 1
        edges[key]["names"].append(name)

    for pl in noim["pls"]:
        name = pl.get("commonName") or pl.get("objectId") or ""
        refs = [c.get("_physicalPort") for c in (pl.get("_physicalConnector") or []) if isinstance(c, dict)]
        dev_ids, missing = _port_devices(refs, port_by_oid, by_id)
        reason = _classify(dev_ids, missing, len(refs))
        if reason:
            skipped.setdefault((PHYSICAL, reason), []).append(name)
        else:
            add(PHYSICAL, dev_ids, name)

    for fre in noim["fres"]:
        if fre.get("nttFreType") != "NC":
            continue
        name = fre.get("commonName") or fre.get("objectId") or ""
        refs = fre.get("_supportingFreRefList") or []
        dev_ids = []
        missing = 0
        for ref in refs:
            xc = fre_by_oid.get(ref)
            params = xc.get("transmissionParameterList") if xc else None
            dev_id = params.get("raVxmId") if isinstance(params, dict) else None
            if dev_id in by_id:
                if dev_id not in dev_ids:
                    dev_ids.append(dev_id)
            else:
                missing += 1
        reason = _classify(dev_ids, missing, len(refs))
        if reason:
            skipped.setdefault((LSP, reason), []).append(name)
        else:
            add(LSP, dev_ids, name)

    warnings = []
    for (kind, reason), names in sorted(skipped.items()):
        shown = "、".join(names[:MAX_NAMES_IN_WARNING])
        more = " ほか%d件" % (len(names) - MAX_NAMES_IN_WARNING) if len(names) > MAX_NAMES_IN_WARNING else ""
        warnings.append("%sを描けません(%s): %d件 [%s%s]" % (KIND_LABEL[kind], reason, len(names), shown, more))
    return [edges[k] for k in order], warnings


def attach_alarms(devices, by_name, alarms):
    """targetDeviceId と装置名の完全一致でアラームを装置に付ける。一致しないアラームのリストを返す。"""
    unmatched = []
    for alarm in alarms:
        dev = by_name.get(alarm["targetDeviceId"])
        if dev is None:
            unmatched.append(alarm)
        else:
            dev["alarms"].append(alarm)
    for dev in devices:
        dev["alarms"].sort(key=lambda a: (a["status"] != "active", -a["alarmLevel"], a["alarmId"]))
        levels = [a["alarmLevel"] for a in dev["alarms"] if a["status"] == "active"]
        dev["severity"] = max(levels) if levels else 0
    return unmatched


def build_graph(noim, alarms):
    """表示用のデータ {devices, edges, warnings, unmatched_alarms, summary} を作る。"""
    devices, by_id, by_name = build_devices(noim["pds"])
    edges, warnings = build_edges(noim, by_id)
    unmatched = attach_alarms(devices, by_name, alarms)

    # 線(物理接続・LSP接続)につながらない装置。新しい接続の規則は足さず、ありのまま「接続なし」として示す
    connected = set()
    for e in edges:
        connected.add(e["source"])
        connected.add(e["target"])
    for d in devices:
        d["isolated"] = d["id"] not in connected

    summary = {
        "devices": len(devices),
        "physical_edges": sum(1 for e in edges if e["kind"] == PHYSICAL),
        "lsp_edges": sum(1 for e in edges if e["kind"] == LSP),
        "alarm_devices": sum(1 for d in devices if d["severity"] > 0),
        "isolated_devices": sum(1 for d in devices if d["isolated"]),
        "severity_devices": dict((str(n), sum(1 for d in devices if d["severity"] == n)) for n in (1, 2, 3)),
        "alarms": len(alarms),
        "active_alarms": sum(1 for a in alarms if a["status"] == "active"),
        "recovered_alarms": sum(1 for a in alarms if a["status"] == "recovered"),
        "unmatched_alarms": len(unmatched),
        "warnings": len(warnings),
    }
    return {"devices": devices, "edges": edges, "warnings": warnings,
            "unmatched_alarms": unmatched, "summary": summary}
