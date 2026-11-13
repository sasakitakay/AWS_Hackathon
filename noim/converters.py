"""入力(ノード/エンティティ/サービス)をNOIMのリソース(辞書)に変換する。

変換の順序と採番の順序は設計書 converters_handler のとおり:
PStruct -> PD -> PPort -> PLink -> LD層TPE/TL -> LAG層FRE/TPE -> LD層TPE(仮想PPort相当) -> NFD -> 仮想PPort
リソースは辞書(キーの順序は設計書の記載順)。
"""

from . import object_id as oid
from .errors import ToolError
from .input_csv import ENTITY_COLUMNS, NODE_COLUMNS, SERVICE_COLUMNS

CE_UNIQUE_ID = u"全国"
SERVICE_PHYSICAL = u"物理(BR)"
SERVICE_LSP = u"LSP詳細(BR)"


# ---------------------------------------------------------------- 共通

def _camel(column):
    return "".join(p[:1].upper() + p[1:] for p in column.split("_"))


def management_info(row, prefix, columns):
    """入力の全項目を nttManagementInfo 用の辞書にする(キーは 接頭辞 + 列名のUpperCamelCase)。

    ただしノードの node_profile_name は nodeProfileName(設計書・仕様書どおり)。
    """
    info = {}
    for col in columns:
        if prefix == "node" and col == "node_profile_name":
            key = "nodeProfileName"
        else:
            key = prefix + _camel(col)
        value = row[col]
        info[key] = list(value) if isinstance(value, list) else value
    return info


def _place(full_address, grid_x, grid_y):
    return [{
        "ID": "1",
        "_localAddress": {"fullAddress": full_address},
        "gridX": grid_x,
        "gridY": grid_y,
    }]


def _label(kind, row):
    """エラーメッセージ用のサービス/ノード/エンティティの表示。"""
    return "%s '%s' (行 %d)" % (kind, row["name"], row.line)


# ---------------------------------------------------------------- PStruct

def _parse_node_name(name):
    parts = name.split(u"・")
    return parts[2] if len(parts) >= 3 else name


def node_unique_id(node):
    """PStructを一意にするためのID。CEは "全国"。"""
    if node["node_type"] == "CE":
        return CE_UNIQUE_ID
    if node["unification_bldg_code"] != "":
        return node["unification_bldg_code"]
    if node["parent_node_group_name"] == u"BR網":
        return node["name"]
    return _parse_node_name(node["name"])


def _pstruct_name(node):
    if node["unification_bldg_code"] != "":
        return node["build_name"]
    if node["parent_node_group_name"] == u"BR網":
        return node["name"]
    return _parse_node_name(node["name"])


def convert_pstruct(nodes, ids):
    """戻り値: (PStructのリスト, {unique_id: PStructのobjectId})"""
    pstructs = []
    unique_dict = {}
    for node in nodes:
        uid = node_unique_id(node)
        if uid in unique_dict:
            continue
        if uid == CE_UNIQUE_ID:
            pstructs.append({
                "commonName": CE_UNIQUE_ID,
                "objectId": oid.CE_PSTRUCT_ID,
                "_resourceSpecification": oid.PR_SPEC_PSTRUCT,
                "_place": _place("SYS=NOIM/Building=CE", "0", "0"),
                "resourceCapacity": [],
                "nttLifecycleStatus": 1,
                "nttManagementInfo": {},
            })
            unique_dict[uid] = oid.CE_PSTRUCT_ID
        else:
            name = _pstruct_name(node)
            object_id = ids.next_id("pStructs")
            pstructs.append({
                "commonName": name,
                "objectId": object_id,
                "_resourceSpecification": oid.PR_SPEC_PSTRUCT,
                "_place": _place(name, node["latitude"] or "0", node["longitude"] or "0"),
                "resourceCapacity": [],
                "nttLifecycleStatus": 1,
                "nttManagementInfo": {},
            })
            unique_dict[uid] = object_id
    return pstructs, unique_dict


# ---------------------------------------------------------------- PD

def convert_pd(nodes, unique_dict, ids):
    pds = []
    for node in nodes:
        is_ce = node["node_type"] == "CE"
        info = management_info(node, "node", NODE_COLUMNS)
        info["nttLadder"] = 1 if is_ce else None
        pds.append({
            "commonName": node["name"],
            "objectId": ids.next_id("pds"),
            "_resourceSpecification": oid.PR_SPEC_PD,
            "resourceCapacity": [],
            "_hardware": {"_physicalConnector": []},
            "nttManagementInfo": info,
            "nttPhysicalStructure": oid.CE_PSTRUCT_ID if is_ce else unique_dict[node_unique_id(node)],
            "nttPhysicalDeviceType": "LOGICAL_CONNECT",
            "nttLifecycleStatus": 1,
        })
    return pds


# ---------------------------------------------------------------- PPort

def convert_pport(entities, pds, ids):
    """エンティティごとにPPortを作り、同じノードのPDの物理コネクタに追加する。"""
    pd_by_node = {}
    for pd in pds:
        pd_by_node.setdefault(pd["nttManagementInfo"]["nodeRaVxmId"], []).append(pd)
    pports = []
    for entity in entities:
        object_id = ids.next_id("pPorts")
        for pd in pd_by_node.get(entity["node_id"], []):
            pd["_hardware"]["_physicalConnector"].append({"_physicalPort": object_id})
        pports.append({
            "commonName": entity["name"],
            "objectId": object_id,
            "_place": _place("", "", ""),
            "_resourceSpecification": oid.PR_SPEC_PPORT,
            "resourceCapacity": [],
            "vendorPortName": entity["name"],
            "nttLifecycleStatus": 1,
            "nttManagementInfo": management_info(entity, "entity", ENTITY_COLUMNS),
        })
    return pports


def _pports_by_entity(pports):
    """{エンティティのra_vxm_id: [PPortのobjectId, ...]}"""
    result = {}
    for p in pports:
        result.setdefault(p["nttManagementInfo"]["entityRaVxmId"], []).append(p["objectId"])
    return result


# ---------------------------------------------------------------- PLink

def convert_plink(services, pports, ids):
    by_entity = _pports_by_entity(pports)
    plinks = []
    for service in services:
        if service["service_profile_name"] != SERVICE_PHYSICAL:
            continue
        connectors = []
        for entity_id in service["client_entity_id_list"]:
            for port_id in by_entity.get(entity_id, []):
                connectors.append({"_physicalPort": port_id})
        plinks.append({
            "commonName": service["name"],
            "objectId": ids.next_id("pls"),
            "_resourceSpecification": oid.PR_SPEC_PLINK,
            "resourceCapacity": [],
            "_physicalConnector": connectors,
            "nttLifecycleStatus": 1,
            "nttManagementInfo": management_info(service, "service", SERVICE_COLUMNS),
        })
    return plinks


# ---------------------------------------------------------------- LD層 TPE / TL

def _first_by_id(entities):
    result = {}
    for e in entities:
        result.setdefault(e["ra_vxm_id"], e)
    return result


def convert_ld_tpe_tl(services, entities, pports, ids):
    """物理(BR)のサービスごとに、クライアントエンティティ2件からTPEを、その2件を結ぶTLを作る。

    戻り値: (TPEのリスト, TLのリスト)
    """
    entity_by_id = _first_by_id(entities)
    port_by_entity = _pports_by_entity(pports)
    tpes = []
    tls = []
    for service in services:
        if service["service_profile_name"] != SERVICE_PHYSICAL:
            continue
        client_ids = service["client_entity_id_list"]
        if len(client_ids) != 2:
            raise ToolError("%s: client_entity_id_list が2件ではありません (%d件)"
                            % (_label("サービス", service), len(client_ids)))
        pair = []
        for entity_id in client_ids:
            entity = entity_by_id.get(entity_id)
            if entity is None:
                raise ToolError("%s: クライアントエンティティが見つかりません (%s)"
                                % (_label("サービス", service), entity_id))
            tpe = {
                "commonName": entity["name"],
                "objectId": ids.next_id("tpes"),
                "_resourceSpecification": oid.LR_SPEC_TPE,
                "resourceCapacity": [],
                "lrStatus": 1,
                "_physicalPortRefList": list(port_by_entity.get(entity["ra_vxm_id"], [])),
                "_encapsulatedLtList": [{
                    "layerProtocolNameList": ["logicalDevice"],
                    "ltType": "TCP",
                    "transmissionParameterList": {
                        "ipAddress": entity["ipv4_address"],
                        "deviceName": entity["node_name"],
                        "raVxmId": entity["ra_vxm_id"],
                    },
                }],
                "tpeType": "PTP",
                "nttServerTpeRefList": [],
            }
            tpes.append(tpe)
            pair.append(tpe)
        tls.append({
            "commonName": service["name"],
            "objectId": ids.next_id("tls"),
            "_resourceSpecification": oid.LR_SPEC_TL,
            "resourceCapacity": [],
            "lrStatus": 1,
            "_aEndTpeRefList": [pair[0]["objectId"]],
            "_zEndTpeRefList": [pair[1]["objectId"]],
            "layerProtocolNameList": ["logicalDevice"],
            "transmissionParameterList": {"raVxmId": service["ra_vxm_id"]},
        })
    return tpes, tls


# ---------------------------------------------------------------- LAG層 FRE / TPE

def _lag_tpe(common_name, object_id, lt_type, params, server_refs):
    return {
        "commonName": common_name,
        "objectId": object_id,
        "_resourceSpecification": oid.LR_SPEC_TPE,
        "resourceCapacity": [],
        "lrStatus": 1,
        "_physicalPortRefList": [],
        "_encapsulatedLtList": [{
            "layerProtocolNameList": ["lag"],
            "ltType": lt_type,
            "transmissionParameterList": params,
        }],
        "tpeType": "CTP",
        "nttServerTpeRefList": server_refs,
    }


def _lag_fre(common_name, object_id, tpe_ids, ra_vxm_id, fre_type, server_connection_refs):
    return {
        "commonName": common_name,
        "objectId": object_id,
        "_resourceSpecification": oid.LR_SPEC_FRE,
        "resourceCapacity": [],
        "lrStatus": 1,
        "_endPointList": [{"_tpeIdRef": t} for t in tpe_ids],
        "_supportingFreRefList": [],
        "freType": "POINT_TO_POINT",
        "layerProtocolName": "lag",
        "transmissionParameterList": {"raVxmId": ra_vxm_id},
        "nttFreType": fre_type,
        "nttServerConnectionRefList": server_connection_refs,
    }


class LagResult(object):
    """LAG層の変換結果(各リストは作成順)。"""

    def __init__(self):
        self.tcps = []
        self.cps = []
        self.ncs = []
        self.lcs = []
        self.xcs = []


def convert_lag(services, entities, tls, ld_tpes, ids):
    """LSP詳細(BR)のサービスごとに、LAG層のTPE(TCP/CP)とFRE(NC/LC/XC)を作る。

    NCは (A側ノード, Z側ノード) ごとに1つ、XCはA側/Z側のノードごとに1つを共有する。
    """
    entity_by_id = _first_by_id(entities)
    tl_by_service = {}
    for tl in tls:
        tl_by_service.setdefault(tl["transmissionParameterList"]["raVxmId"], tl)
    ld_tpe_by_id = {t["objectId"]: t for t in ld_tpes}
    lag_tpe_by_id = {}
    nc_map = {}
    a_xc_map = {}
    z_xc_map = {}
    result = LagResult()

    def new_tcp(svc):
        tcp = _lag_tpe(svc["name"], ids.next_id("tpes"), "TCP",
                       {"ipAddress": "", "deviceName": "", "raVxmId": ""}, [])
        result.tcps.append(tcp)
        lag_tpe_by_id[tcp["objectId"]] = tcp
        return tcp

    def tcp_of_xc(xc):
        for ep in xc["_endPointList"]:
            tpe = lag_tpe_by_id[ep["_tpeIdRef"]]
            if tpe["_encapsulatedLtList"][0]["ltType"] == "TCP":
                return tpe
        raise ToolError("XC '%s' にTCPの端点がありません" % xc["commonName"])

    def new_cp(ld_tpe):
        params = ld_tpe["_encapsulatedLtList"][0]["transmissionParameterList"]
        cp = _lag_tpe(ld_tpe["commonName"], ids.next_id("tpes"), "CP",
                      {"ipAddress": params["ipAddress"], "deviceName": params["deviceName"],
                       "raVxmId": params["raVxmId"]},
                      [ld_tpe["objectId"]])
        result.cps.append(cp)
        lag_tpe_by_id[cp["objectId"]] = cp
        return cp

    for svc in services:
        if svc["service_profile_name"] != SERVICE_LSP:
            continue
        client_ids = svc["client_entity_id_list"]
        if not client_ids:
            continue
        label = _label("サービス", svc)
        if len(client_ids) != 2:
            raise ToolError("%s: client_entity_id_list が2件ではありません (%d件)" % (label, len(client_ids)))
        ends = []
        for entity_id in client_ids:
            ent = entity_by_id.get(entity_id)
            if ent is None:
                raise ToolError("%s: クライアントエンティティが見つかりません (%s)" % (label, entity_id))
            ends.append(ent)
        a_node = ends[0]["node_id"]
        z_node = ends[1]["node_id"]

        # NC(必要なら TCP も)
        nc = nc_map.get((a_node, z_node))
        nc_is_new = nc is None
        if nc_is_new:
            a_tcp = tcp_of_xc(a_xc_map[a_node]) if a_node in a_xc_map else new_tcp(svc)
            z_tcp = tcp_of_xc(z_xc_map[z_node]) if z_node in z_xc_map else new_tcp(svc)
            nc = _lag_fre(svc["name"], ids.next_id("fres"),
                          [a_tcp["objectId"], z_tcp["objectId"]], svc["ra_vxm_id"], "NC", [])
            nc_map[(a_node, z_node)] = nc
            result.ncs.append(nc)

        # 下位レイヤ(LD層)のTLを探し、その両端のLD層TPEからCPを2件作る
        lower_ids = svc["network_service_id_list"]
        if not lower_ids:
            raise ToolError("%s: network_service_id_list が空です(下位のTLを特定できません)" % label)
        tl = tl_by_service.get(lower_ids[0])
        if tl is None:
            raise ToolError("%s: network_service_id_list の1件目に対応するTLがありません (%s)" % (label, lower_ids[0]))
        a_ld = ld_tpe_by_id.get(tl["_aEndTpeRefList"][0])
        z_ld = ld_tpe_by_id.get(tl["_zEndTpeRefList"][0])
        if a_ld is None or z_ld is None:
            raise ToolError("%s: TL '%s' の端点のLD層TPEが見つかりません" % (label, tl["commonName"]))
        a_cp = new_cp(a_ld)
        z_cp = new_cp(z_ld)
        if a_node in a_xc_map:
            a_xc_map[a_node]["_endPointList"].append({"_tpeIdRef": a_cp["objectId"]})
        if z_node in z_xc_map:
            z_xc_map[z_node]["_endPointList"].append({"_tpeIdRef": z_cp["objectId"]})

        # LC
        result.lcs.append(_lag_fre(svc["name"], ids.next_id("fres"),
                                   [a_cp["objectId"], z_cp["objectId"]], svc["ra_vxm_id"], "LC",
                                   [tl["objectId"]]))

        # XC(A側/Z側のノードで未作成のときだけ)と、NCの _supportingFreRefList
        if nc_is_new:
            if a_node not in a_xc_map:
                xc = _lag_fre(svc["name"], ids.next_id("fres"),
                              [a_tcp["objectId"], a_cp["objectId"]], a_node, "XC", [])
                a_xc_map[a_node] = xc
                result.xcs.append(xc)
            if z_node not in z_xc_map:
                xc = _lag_fre(svc["name"], ids.next_id("fres"),
                              [z_tcp["objectId"], z_cp["objectId"]], z_node, "XC", [])
                z_xc_map[z_node] = xc
                result.xcs.append(xc)
            nc["_supportingFreRefList"] = [a_xc_map[a_node]["objectId"], z_xc_map[z_node]["objectId"]]
    return result


# ---------------------------------------------------------------- LD層 TPE(仮想PPort相当)

def convert_ld_tpe_vport(tcps, ids):
    """LAG層TCPごとにLD層のTPEを作り、TCPの nttServerTpeRefList にそのobjectIdを設定する。"""
    tpes = []
    for tcp in tcps:
        lt = tcp["_encapsulatedLtList"][0]
        params = lt["transmissionParameterList"]
        tpe = {
            "commonName": tcp["commonName"],
            "objectId": ids.next_id("tpes"),
            "_resourceSpecification": oid.LR_SPEC_TPE,
            "resourceCapacity": [],
            "lrStatus": 1,
            "_physicalPortRefList": [],
            "_encapsulatedLtList": [{
                "layerProtocolNameList": ["logicalDevice"],
                "ltType": lt["ltType"],
                "transmissionParameterList": {
                    "ipAddress": params["ipAddress"],
                    "deviceName": params["deviceName"],
                    "raVxmId": params["raVxmId"],
                },
            }],
            "tpeType": "PTP",
            "nttServerTpeRefList": [],
        }
        tcp["nttServerTpeRefList"] = [tpe["objectId"]]
        tpes.append(tpe)
    return tpes


# ---------------------------------------------------------------- NFD

def convert_nfd(xcs, tpes, ids):
    """XCごとにNFDを作る。_edgeTpeRefList は、XCの各端点のTPEの nttServerTpeRefList を集めたもの。"""
    tpe_by_id = {t["objectId"]: t for t in tpes}
    nfds = []
    for xc in xcs:
        edge = []
        for ep in xc["_endPointList"]:
            tpe = tpe_by_id.get(ep["_tpeIdRef"])
            if tpe is None:
                raise ToolError("XC '%s' の端点のTPEが見つかりません (%s)" % (xc["commonName"], ep["_tpeIdRef"]))
            edge.extend(tpe["nttServerTpeRefList"])
        nfds.append({
            "commonName": xc["commonName"],
            "objectId": ids.next_id("nfds"),
            "_resourceSpecification": oid.LR_SPEC_NFD,
            "resourceCapacity": [],
            "lrStatus": 1,
            "_edgeTpeRefList": edge,
            "_layerProtocolParameters": [{
                "layerProtocolName": "logicalDevice",
                "transmissionParameterList": {},
            }],
            "layerProtocolNameList": ["logicalDevice"],
            "nfdRole": "ROUTING_AREA",
            "nttSupportableClientLayers": ["lag"],
        })
    return nfds


# ---------------------------------------------------------------- 仮想PPort

def convert_vport(xcs, tpes, pds, ids):
    """XCごとに仮想PPortを作り、PDの物理コネクタとLD層TPE(仮想PPort相当)の _physicalPortRefList に追加する。

    tpes は、すべてのTPE(LD層・LAG層)のリスト。
    """
    tpe_by_id = {t["objectId"]: t for t in tpes}
    pd_by_port = {}
    for pd in pds:
        for conn in pd["_hardware"]["_physicalConnector"]:
            pd_by_port.setdefault(conn["_physicalPort"], pd)
    vports = []
    for xc in xcs:
        pd = None
        vtpe = None
        for ep in xc["_endPointList"]:
            tpe = tpe_by_id[ep["_tpeIdRef"]]
            if tpe["_encapsulatedLtList"][0]["ltType"] == "CP":
                if pd is not None:
                    continue
                for server_id in tpe["nttServerTpeRefList"]:
                    for port_id in tpe_by_id[server_id]["_physicalPortRefList"]:
                        if port_id in pd_by_port:
                            pd = pd_by_port[port_id]
                            break
                    if pd is not None:
                        break
            else:
                if tpe["nttServerTpeRefList"]:
                    vtpe = tpe_by_id[tpe["nttServerTpeRefList"][0]]
        if pd is None or vtpe is None:
            raise ToolError("XC '%s' の仮想PPortを作れません(%s が見つかりません)"
                            % (xc["commonName"], "PD" if pd is None else "LD層TPE(仮想PPort相当)"))
        object_id = ids.next_id("pPorts")
        vports.append({
            "commonName": "vPort",
            "objectId": object_id,
            "_place": _place("", "", ""),
            "_resourceSpecification": oid.PR_SPEC_PPORT,
            "resourceCapacity": [],
            "vendorPortName": "vPort",
            "nttLifecycleStatus": 1,
            "nttManagementInfo": {},
        })
        pd["_hardware"]["_physicalConnector"].append({"_physicalPort": object_id})
        vtpe["_physicalPortRefList"].append(object_id)
    return vports


# ---------------------------------------------------------------- 全体

# 出力ファイルの種類(resourceInfo_<種類>.csv)の順序
RESOURCE_KINDS = ("nfds", "fres", "tpes", "tls", "pPorts", "pds", "pls", "pStructs")


def convert_all(nodes, entities, services):
    """3種の入力から、リソースの種類ごとのリスト {種類: [辞書, ...]} を作る。

    objectIdは毎回1から採番する。
    """
    ids = oid.ObjectIdManager()
    pstructs, unique_dict = convert_pstruct(nodes, ids)
    pds = convert_pd(nodes, unique_dict, ids)
    pports = convert_pport(entities, pds, ids)
    plinks = convert_plink(services, pports, ids)
    ld_tpes, tls = convert_ld_tpe_tl(services, entities, pports, ids)
    lag = convert_lag(services, entities, tls, ld_tpes, ids)
    vport_tpes = convert_ld_tpe_vport(lag.tcps, ids)
    tpes = ld_tpes + lag.tcps + lag.cps + vport_tpes
    nfds = convert_nfd(lag.xcs, tpes, ids)
    vports = convert_vport(lag.xcs, tpes, pds, ids)
    return {
        "nfds": nfds,
        "fres": lag.ncs + lag.lcs + lag.xcs,
        "tpes": tpes,
        "tls": tls,
        "pPorts": pports + vports,
        "pds": pds,
        "pls": plinks,
        "pStructs": pstructs,
    }
