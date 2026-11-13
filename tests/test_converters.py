"""NOIM変換(PStruct/PD/PPort/PLink/LD層TPE・TL/LAG層/NFD/仮想PPort)のテスト(FR2)。"""

import unittest

from noim import converters as cv
from noim import object_id as oid
from noim.errors import ToolError
from noim.input_csv import ENTITY_COLUMNS, NODE_COLUMNS, SERVICE_COLUMNS, Row
from noim.object_id import ObjectIdManager

# 外部インタフェース仕様書(1.8 PD、1.7 PPort、1.9 PLink)の nttManagementInfo のキー一覧
PD_KEYS = """nodeRaVxmId nodeRaJobId nodeRaUpdatedAt nodeRaCreatedAt nodeName nodeNodeType
nodeParentNodeGroupId nodeParentNodeGroupName nodeParentNodeId nodeParentNodeName nodeProductName
nodeProductVersion nodeDescription nodeVendorName nodeProtocol nodeNodeProfileId nodeProfileName
nodeUsername nodePassword nodeConnectionType nodePrimaryPort nodeSecondaryPort nodeExternalId
nodePlugIn nodeTelemetryUsername nodeTelemetryPassword nodeTelemetryPort nodeScopeIdList
nodeScopeNameList nodeRequestsPerTimePeriod nodeAdminStatus nodeLatitude nodeLongitude nodeAddress
nodeLocation nodeMemo nodeOperStatus nodeTimezone nodeLastAlarmSyncAt nodePrimaryIpv4Address
nodePrimaryIpv6Address nodeSecondaryIpv4Address nodeSecondaryIpv6Address nodeUnificationBldgCode
nodeBuildName nodeAreaName nodePrefecture nodeFloorRack nodeHostName nodeNeopsNumber
nodeNeopsSerialNumber nodeNeopsTrafficUrl nodeNeopsTopUrl nodeControllerVipAddress nodeNeopsIpAddress
nodeNodeTemplate nodeApplicationMonitorTemplate nodeSimpleControlTemplate nttLadder""".split()
PPORT_KEYS = """entityRaVxmId entityRaJobId entityRaUpdatedAt entityRaCreatedAt entityName
entityDescription entityMemo entityNodeName entityNodeId entityEntityProfileName entityEntityProfileId
entityParentEntityName entityParentEntityId entityType entityMacAddress entityIpv4Address
entityIpv6Address entityAdminStatus entityOperStatus entityMtu entitySpeed entityLinkId entityLinkName
entityServiceId entityServiceName entityScopeIdList entityScopeNameList entityExternalId entitySnmpOid
entitySnmpIndex entitySnmpType entitySnmpTypeId entityCreatedBy""".split()
PLINK_KEYS = """serviceRaVxmId serviceRaJobId serviceRaUpdatedAt serviceRaCreatedAt serviceName
serviceDescription serviceMemo serviceServiceProfileId serviceServiceProfileName serviceAdminStatus
serviceOperStatus serviceProtectionStatus serviceExternalId serviceNetworkEntityIdList
serviceNetworkEntityNameList serviceClientEntityIdList serviceClientEntityNameList
serviceNetworkServiceIdList serviceNetworkServiceNameList serviceNetworkProtectionServiceIdList
serviceNetworkProtectionServiceNameList serviceSeverity servicePriority serviceType
serviceProtectionType serviceServiceStatus""".split()


def make_row(columns, line=2, **values):
    """入力の1行(Row)。列名は引数で指定、省略した列は空(リスト列は空配列)。"""
    row = Row()
    row.line = line
    for c in columns:
        row[c] = [] if c.endswith("_list") else ""
    row.update(values)
    return row


def node(ra_id, name, node_type="CR2", **kw):
    kw.setdefault("parent_node_group_name", u"BR網")
    return make_row(NODE_COLUMNS, ra_vxm_id=ra_id, name=name, node_type=node_type, **kw)


def entity(ra_id, name, node_id, **kw):
    return make_row(ENTITY_COLUMNS, ra_vxm_id=ra_id, name=name, node_id=node_id,
                    node_name="n-" + node_id, **kw)


def service(ra_id, name, profile, clients=(), network_services=(), **kw):
    return make_row(SERVICE_COLUMNS, ra_vxm_id=ra_id, name=name, service_profile_name=profile,
                    client_entity_id_list=list(clients),
                    network_service_id_list=list(network_services), **kw)


class PStructTest(unittest.TestCase):
    def test_unique_id_rules(self):
        self.assertEqual(cv.node_unique_id(node("1", "x", node_type="CE")), u"全国")
        self.assertEqual(cv.node_unique_id(node("1", "a・b・c", unification_bldg_code="U1")), "U1")
        self.assertEqual(cv.node_unique_id(node("1", "a・b・c", parent_node_group_name=u"BR網")), "a・b・c")
        self.assertEqual(cv.node_unique_id(node("1", "a・b・c", parent_node_group_name=u"AR網")), "c")
        self.assertEqual(cv.node_unique_id(node("1", "a・b", parent_node_group_name=u"AR網")), "a・b")

    def test_one_pstruct_per_unique_id_and_single_ce(self):
        nodes = [
            node("1", "n1", unification_bldg_code="U1", build_name=u"ビルA", latitude="35.1", longitude="139.2"),
            node("2", "n2", unification_bldg_code="U1", build_name=u"ビルA"),
            node("3", "n3"),
            node("4", "ce1", node_type="CE"),
            node("5", "ce2", node_type="CE"),
        ]
        ids = ObjectIdManager()
        pstructs, uniq = cv.convert_pstruct(nodes, ids)
        self.assertEqual([p["commonName"] for p in pstructs], [u"ビルA", "n3", u"全国"])
        a = pstructs[0]
        self.assertEqual(a["objectId"], "http://localhost:3000/pStructs/system_00000001")
        self.assertEqual(a["_place"][0]["_localAddress"]["fullAddress"], u"ビルA")
        self.assertEqual((a["_place"][0]["gridX"], a["_place"][0]["gridY"]), ("35.1", "139.2"))
        self.assertEqual(pstructs[1]["objectId"], "http://localhost:3000/pStructs/system_00000002")
        self.assertEqual(pstructs[1]["_place"][0]["gridX"], "0")  # 緯度が空なら "0"
        ce = pstructs[2]
        self.assertEqual(ce["objectId"], oid.CE_PSTRUCT_ID)
        self.assertEqual(ce["_place"][0]["_localAddress"]["fullAddress"], "SYS=NOIM/Building=CE")
        self.assertEqual(uniq["U1"], a["objectId"])
        self.assertEqual(uniq[u"全国"], oid.CE_PSTRUCT_ID)
        # CEは採番しない: 次の採番は3番
        self.assertTrue(ids.next_id("pStructs").endswith("system_00000003"))
        self.assertEqual(list(a.keys()), [
            "commonName", "objectId", "_resourceSpecification", "_place", "resourceCapacity",
            "nttLifecycleStatus", "nttManagementInfo"])


class PdPportPlinkTest(unittest.TestCase):
    def setUp(self):
        self.nodes = [node("n1", "node1", unification_bldg_code="U1", build_name="B1"),
                      node("n2", "ce", node_type="CE")]
        self.entities = [entity("e1", "port1", "n1"), entity("e2", "port2", "n1"),
                         entity("e3", "port3", "n2"), entity("e4", "lost", "nX")]
        self.ids = ObjectIdManager()
        _p, uniq = cv.convert_pstruct(self.nodes, self.ids)
        self.pds = cv.convert_pd(self.nodes, uniq, self.ids)

    def test_pd(self):
        pd, ce = self.pds
        self.assertEqual(pd["objectId"], "http://localhost:3000/pds/system_00000001")
        self.assertEqual(pd["_resourceSpecification"], oid.PR_SPEC_PD)
        self.assertEqual(pd["nttPhysicalStructure"], "http://localhost:3000/pStructs/system_00000001")
        self.assertIsNone(pd["nttManagementInfo"]["nttLadder"])
        self.assertEqual(pd["_hardware"], {"_physicalConnector": []})
        self.assertEqual(ce["nttPhysicalStructure"], oid.CE_PSTRUCT_ID)
        self.assertEqual(ce["nttManagementInfo"]["nttLadder"], 1)
        self.assertEqual(pd["nttPhysicalDeviceType"], "LOGICAL_CONNECT")
        self.assertEqual(list(pd["nttManagementInfo"].keys()), PD_KEYS)

    def test_pport_links_to_pd(self):
        pports = cv.convert_pport(self.entities, self.pds, self.ids)
        self.assertEqual([p["objectId"][-8:] for p in pports], ["00000001", "00000002", "00000003", "00000004"])
        self.assertEqual(self.pds[0]["_hardware"]["_physicalConnector"],
                         [{"_physicalPort": pports[0]["objectId"]}, {"_physicalPort": pports[1]["objectId"]}])
        self.assertEqual(self.pds[1]["_hardware"]["_physicalConnector"], [{"_physicalPort": pports[2]["objectId"]}])
        # 一致するPDがないエンティティは、どのPDにも追加しない(PPortは作る)
        self.assertEqual(pports[3]["commonName"], "lost")
        self.assertEqual(pports[0]["vendorPortName"], "port1")
        self.assertEqual(list(pports[0]["nttManagementInfo"].keys()), PPORT_KEYS)
        self.assertEqual(pports[0]["_place"][0]["_localAddress"], {"fullAddress": ""})

    def test_plink(self):
        pports = cv.convert_pport(self.entities, self.pds, self.ids)
        services = [
            service("s1", "phys", u"物理(BR)", clients=["e2", "e1"]),
            service("s2", "vpn", u"VPN回線(BR)", clients=["e1", "e2"]),
        ]
        plinks = cv.convert_plink(services, pports, self.ids)
        self.assertEqual(len(plinks), 1)
        pl = plinks[0]
        self.assertEqual(pl["objectId"], "http://localhost:3000/pls/system_00000001")
        self.assertEqual(pl["_physicalConnector"],
                         [{"_physicalPort": pports[1]["objectId"]}, {"_physicalPort": pports[0]["objectId"]}])
        self.assertEqual(list(pl["nttManagementInfo"].keys()), PLINK_KEYS)
        self.assertEqual(pl["nttManagementInfo"]["serviceClientEntityIdList"], ["e2", "e1"])


class LdTpeTlTest(unittest.TestCase):
    def setUp(self):
        self.nodes = [node("n1", "node1"), node("n2", "node2")]
        self.entities = [entity("e1", "port1", "n1", ipv4_address="10.0.0.1"), entity("e2", "port2", "n2")]
        self.ids = ObjectIdManager()
        _p, uniq = cv.convert_pstruct(self.nodes, self.ids)
        pds = cv.convert_pd(self.nodes, uniq, self.ids)
        self.pports = cv.convert_pport(self.entities, pds, self.ids)

    def test_tpe_and_tl(self):
        services = [service("s1", "phys", u"物理(BR)", clients=["e1", "e2"]),
                    service("s2", "other", u"VPN回線(BR)", clients=["e1", "e2"])]
        tpes, tls = cv.convert_ld_tpe_tl(services, self.entities, self.pports, self.ids)
        self.assertEqual(len(tpes), 2)
        self.assertEqual(len(tls), 1)
        a, z = tpes
        self.assertEqual(a["objectId"], "http://localhost:3000/tpes/system_00000001")
        self.assertEqual(a["commonName"], "port1")
        self.assertEqual(a["_physicalPortRefList"], [self.pports[0]["objectId"]])
        self.assertEqual(a["tpeType"], "PTP")
        self.assertEqual(a["nttServerTpeRefList"], [])
        lt = a["_encapsulatedLtList"][0]
        self.assertEqual(lt["layerProtocolNameList"], ["logicalDevice"])
        self.assertEqual(lt["ltType"], "TCP")
        self.assertEqual(lt["transmissionParameterList"],
                         {"ipAddress": "10.0.0.1", "deviceName": "n-n1", "raVxmId": "e1"})
        tl = tls[0]
        self.assertEqual(tl["objectId"], "http://localhost:3000/tls/system_00000001")
        self.assertEqual(tl["_aEndTpeRefList"], [a["objectId"]])
        self.assertEqual(tl["_zEndTpeRefList"], [z["objectId"]])
        self.assertEqual(tl["transmissionParameterList"], {"raVxmId": "s1"})
        self.assertEqual(tl["_resourceSpecification"], oid.LR_SPEC_TL)

    def test_errors_name_the_service(self):
        for clients in (["e1"], ["e1", "e2", "e1"], ["e1", "nope"]):
            svc = service("s1", u"壊れたサービス", u"物理(BR)", clients=clients)
            with self.assertRaises(ToolError) as cm:
                cv.convert_ld_tpe_tl([svc], self.entities, self.pports, ObjectIdManager())
            self.assertIn(u"壊れたサービス", str(cm.exception))


class LagAndVportTest(unittest.TestCase):
    """LAG層・NFD・仮想PPortを、3ノード・3本のLSP詳細(BR)の小さなデータで確認する。"""

    def build(self, lsp_services=None):
        nodes = [node("n1", "node1"), node("n2", "node2"), node("n3", "node3")]
        entities = [
            entity("e1", "port1", "n1"), entity("e2", "port2", "n2"),
            entity("e3", "port3", "n1"), entity("e4", "port4", "n3"),
            entity("L1", "Lag 1", "n1"), entity("L2", "Lag 2", "n2"),
            entity("L3", "Lag 3", "n1"), entity("L4", "Lag 4", "n3"),
        ]
        services = [
            service("P1", "phys1", u"物理(BR)", clients=["e1", "e2"]),
            service("P2", "phys2", u"物理(BR)", clients=["e3", "e4"]),
        ]
        if lsp_services is None:
            lsp_services = [
                service("S1", "lsp1", u"LSP詳細(BR)", clients=["L1", "L2"], network_services=["P1"]),
                service("S2", "lsp2", u"LSP詳細(BR)", clients=["L3", "L4"], network_services=["P2"]),
                service("S3", "lsp3", u"LSP詳細(BR)", clients=["L1", "L2"], network_services=["P1"]),
            ]
        return nodes, entities, services + lsp_services

    @staticmethod
    def i(kind, n):
        return "http://localhost:3000/%s/system_%08d" % (kind, n)

    def by_id(self, items):
        return {x["objectId"]: x for x in items}

    def test_counts_and_numbering(self):
        r = cv.convert_all(*self.build())
        self.assertEqual({k: len(v) for k, v in r.items()}, {
            "nfds": 3, "fres": 8, "tpes": 16, "tls": 2, "pPorts": 11, "pds": 3, "pls": 2, "pStructs": 3})
        # 行順: FREは NC -> LC -> XC
        self.assertEqual([f["nttFreType"] for f in r["fres"]], ["NC"] * 2 + ["LC"] * 3 + ["XC"] * 3)
        self.assertEqual([f["objectId"] for f in r["fres"]],
                         [self.i("fres", n) for n in (1, 5, 2, 6, 8, 3, 4, 7)])
        # TPEは LD層(物理由来) -> TCP -> CP -> LD層(仮想PPort相当)
        self.assertEqual([t["objectId"] for t in r["tpes"]],
                         [self.i("tpes", n) for n in (1, 2, 3, 4, 5, 6, 9, 7, 8, 10, 11, 12, 13, 14, 15, 16)])
        self.assertEqual([t["_encapsulatedLtList"][0]["ltType"] for t in r["tpes"]],
                         ["TCP"] * 4 + ["TCP"] * 3 + ["CP"] * 6 + ["TCP"] * 3)
        self.assertEqual([t["_encapsulatedLtList"][0]["layerProtocolNameList"][0] for t in r["tpes"]],
                         ["logicalDevice"] * 4 + ["lag"] * 9 + ["logicalDevice"] * 3)

    def test_nc_lc_xc(self):
        r = cv.convert_all(*self.build())
        fre = self.by_id(r["fres"])
        nc1, nc5 = fre[self.i("fres", 1)], fre[self.i("fres", 5)]
        # NCの端点は A側TCP / Z側TCP。2本目のNCは、A側(n1)のTCP(tpes 5)を共有する
        self.assertEqual([e["_tpeIdRef"] for e in nc1["_endPointList"]], [self.i("tpes", 5), self.i("tpes", 6)])
        self.assertEqual([e["_tpeIdRef"] for e in nc5["_endPointList"]], [self.i("tpes", 5), self.i("tpes", 9)])
        self.assertEqual(nc1["_supportingFreRefList"], [self.i("fres", 3), self.i("fres", 4)])
        self.assertEqual(nc5["_supportingFreRefList"], [self.i("fres", 3), self.i("fres", 7)])
        self.assertEqual((nc1["freType"], nc1["layerProtocolName"], nc1["commonName"]),
                         ("POINT_TO_POINT", "lag", "lsp1"))
        self.assertEqual(nc1["transmissionParameterList"], {"raVxmId": "S1"})
        # LC: 端点はCP2件、nttServerConnectionRefList はTL。3本目は同じTLを使うがNCは増えない
        lc2, lc8 = fre[self.i("fres", 2)], fre[self.i("fres", 8)]
        self.assertEqual([e["_tpeIdRef"] for e in lc2["_endPointList"]], [self.i("tpes", 7), self.i("tpes", 8)])
        self.assertEqual(lc2["nttServerConnectionRefList"], [self.i("tls", 1)])
        self.assertEqual([e["_tpeIdRef"] for e in lc8["_endPointList"]], [self.i("tpes", 12), self.i("tpes", 13)])
        self.assertEqual(lc8["nttServerConnectionRefList"], [self.i("tls", 1)])
        # XC: ノードごとに1つ。後続サービスのCPは既存XCの端点に追加される
        xc3, xc4, xc7 = fre[self.i("fres", 3)], fre[self.i("fres", 4)], fre[self.i("fres", 7)]
        ends = lambda x: [e["_tpeIdRef"] for e in x["_endPointList"]]
        self.assertEqual(ends(xc3), [self.i("tpes", n) for n in (5, 7, 10, 12)])
        self.assertEqual(ends(xc4), [self.i("tpes", n) for n in (6, 8, 13)])
        self.assertEqual(ends(xc7), [self.i("tpes", 9), self.i("tpes", 11)])
        self.assertEqual(xc3["transmissionParameterList"], {"raVxmId": "n1"})
        self.assertEqual(xc3["nttFreType"], "XC")
        self.assertEqual(xc3["nttServerConnectionRefList"], [])

    def test_tpes_lag_layer(self):
        r = cv.convert_all(*self.build())
        tpe = self.by_id(r["tpes"])
        tcp5 = tpe[self.i("tpes", 5)]
        self.assertEqual(tcp5["commonName"], "lsp1")
        self.assertEqual(tcp5["tpeType"], "CTP")
        self.assertEqual(tcp5["_encapsulatedLtList"][0]["transmissionParameterList"],
                         {"ipAddress": "", "deviceName": "", "raVxmId": ""})
        # TCPの nttServerTpeRefList は LD層TPE(仮想PPort相当)
        self.assertEqual(tcp5["nttServerTpeRefList"], [self.i("tpes", 14)])
        cp7 = tpe[self.i("tpes", 7)]
        self.assertEqual(cp7["commonName"], "port1")
        self.assertEqual(cp7["_encapsulatedLtList"][0]["ltType"], "CP")
        self.assertEqual(cp7["_encapsulatedLtList"][0]["transmissionParameterList"]["raVxmId"], "e1")
        self.assertEqual(cp7["nttServerTpeRefList"], [self.i("tpes", 1)])
        vt = tpe[self.i("tpes", 14)]
        self.assertEqual(vt["commonName"], "lsp1")
        self.assertEqual(vt["tpeType"], "PTP")
        self.assertEqual(vt["_encapsulatedLtList"][0]["layerProtocolNameList"], ["logicalDevice"])
        self.assertEqual(vt["_encapsulatedLtList"][0]["ltType"], "TCP")

    def test_nfd(self):
        r = cv.convert_all(*self.build())
        nfd1, nfd2, nfd3 = r["nfds"]
        self.assertEqual(nfd1["objectId"], self.i("nfds", 1))
        self.assertEqual(nfd1["commonName"], "lsp1")  # XC(fres 3)の名前
        self.assertEqual(nfd1["_edgeTpeRefList"][0], self.i("tpes", 14))
        self.assertEqual(set(nfd1["_edgeTpeRefList"]), set(self.i("tpes", n) for n in (14, 1, 3)))
        self.assertEqual(nfd3["_edgeTpeRefList"], [self.i("tpes", 16), self.i("tpes", 4)])
        self.assertEqual(nfd1["nfdRole"], "ROUTING_AREA")
        self.assertEqual(nfd1["nttSupportableClientLayers"], ["lag"])
        self.assertEqual(nfd1["_layerProtocolParameters"],
                         [{"layerProtocolName": "logicalDevice", "transmissionParameterList": {}}])

    def test_vport_links(self):
        r = cv.convert_all(*self.build())
        vports = r["pPorts"][8:]
        self.assertEqual([v["objectId"] for v in vports], [self.i("pPorts", n) for n in (9, 10, 11)])
        self.assertEqual(vports[0]["commonName"], "vPort")
        self.assertEqual(vports[0]["vendorPortName"], "vPort")
        self.assertEqual(vports[0]["nttManagementInfo"], {})
        pd = self.by_id(r["pds"])
        tpe = self.by_id(r["tpes"])
        # XC3(node1)->pports 9、XC4(node2)->10、XC7(node3)->11 を、各ノードのPDと仮想PPort相当のTPEに追加
        for port, pd_n, tpe_n in ((9, 1, 14), (10, 2, 15), (11, 3, 16)):
            self.assertEqual(pd[self.i("pds", pd_n)]["_hardware"]["_physicalConnector"][-1],
                             {"_physicalPort": self.i("pPorts", port)})
            self.assertEqual(tpe[self.i("tpes", tpe_n)]["_physicalPortRefList"], [self.i("pPorts", port)])

    def test_skips_and_errors(self):
        # client_entity_id_list が空のLSPは読み飛ばす
        r = cv.convert_all(*self.build([service("S1", "empty", u"LSP詳細(BR)")]))
        self.assertEqual((len(r["fres"]), len(r["nfds"])), (0, 0))
        # 件数が2件でない / 下位TLが特定できない場合は、サービス名を示してエラー
        bad = [
            service("S1", u"一件だけ", u"LSP詳細(BR)", clients=["L1"], network_services=["P1"]),
            service("S1", u"下位なし", u"LSP詳細(BR)", clients=["L1", "L2"]),
            service("S1", u"下位不明", u"LSP詳細(BR)", clients=["L1", "L2"], network_services=["zzz"]),
            service("S1", u"エンティティ不明", u"LSP詳細(BR)", clients=["L1", "zzz"], network_services=["P1"]),
        ]
        for svc in bad:
            with self.assertRaises(ToolError) as cm:
                cv.convert_all(*self.build([svc]))
            self.assertIn(svc["name"], str(cm.exception))

    def test_vport_error_when_no_pd(self):
        nodes, entities, services = self.build()
        entities = [e for e in entities if e["ra_vxm_id"] != "e2"] + [entity("e2", "port2", "nX")]
        with self.assertRaises(ToolError) as cm:
            cv.convert_all(nodes, entities, services)
        self.assertIn("lsp1", str(cm.exception))

    def test_restart_numbering_each_run(self):
        args = self.build()
        first = cv.convert_all(*args)
        second = cv.convert_all(*self.build())
        self.assertEqual([x["objectId"] for x in first["tpes"]], [x["objectId"] for x in second["tpes"]])


if __name__ == "__main__":
    unittest.main()
