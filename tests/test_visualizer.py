"""NOIM構成図の可視化のテスト(FR1〜FR6)。入出力は一時ディレクトリで行う。"""

import contextlib
import csv
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

import noim_converter
import visualizer
from noim.output_csv import file_name, to_csv_bytes
from noim_viz.errors import VizError
from noim_viz.graph import build_graph
from noim_viz.html_out import render_html
from noim_viz.layout import HEIGHT, NODE_BOX_H, WIDTH, compute_layout, label_width, layout_graph, short_label
from noim_viz.loader import load_alarms, load_noim

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_INPUT = os.path.join(ROOT, u"入力ファイル")
REAL_ALARMS = os.path.join(ROOT, u"アラーム", "alarm_sample.json")
REAL_NOIM = os.path.join(ROOT, "noim_output_sample")
SECRET = "SECRET-PW-12345"


def pd(n, name, node_type="CER1"):
    return {"commonName": name, "objectId": "pd%d" % n,
            "nttManagementInfo": {"nodeRaVxmId": "node%d" % n, "nodeNodeType": node_type,
                                  "nodePassword": SECRET, "nodeUsername": "user-" + SECRET}}


def pport(n, node_n):
    info = {"entityNodeId": "node%d" % node_n} if node_n else {}
    return {"commonName": "port%d" % n, "objectId": "pp%d" % n, "nttManagementInfo": info}


def plink(n, ports):
    return {"commonName": "link%d" % n, "objectId": "pl%d" % n,
            "_physicalConnector": [{"_physicalPort": "pp%d" % p} for p in ports]}


def xc(n, node_n):
    return {"commonName": "xc%d" % n, "objectId": "xc%d" % n, "nttFreType": "XC",
            "transmissionParameterList": {"raVxmId": "node%d" % node_n}}


def nc(n, refs):
    return {"commonName": "nc%d" % n, "objectId": "nc%d" % n, "nttFreType": "NC",
            "_supportingFreRefList": refs}


def sample_noim():
    """装置 A(1) B(2) C(3) D(4, つながりなし)。物理: A-B 2本, B-C 1本, 描けない2本。LSP: A-B, B-C, 描けない1本。"""
    return {
        "pds": [pd(1, u"装置A"), pd(2, u"装置B"), pd(3, u"装置C"), pd(4, u"装置D", "CE")],
        "pPorts": [pport(1, 1), pport(2, 2), pport(3, 2), pport(4, 3), pport(5, 1), pport(6, None)],
        "pls": [plink(1, [1, 2]), plink(2, [5, 3]), plink(3, [3, 4]),
                plink(4, [1, 5]), plink(5, [4, 6])],
        "fres": [xc(1, 1), xc(2, 2), xc(3, 3),
                 nc(1, ["xc1", "xc2"]), nc(2, ["xc2", "xc3"]), nc(3, ["xc1", "nothing"]),
                 {"commonName": "lc1", "objectId": "lc1", "nttFreType": "LC"}],
    }


def write_noim(d, noim):
    for kind, rows in noim.items():
        with open(os.path.join(d, file_name(kind)), "wb") as f:
            f.write(to_csv_bytes(rows))


def alarm(n, name, level, status, target):
    return {"alarmId": "ALM-%05d" % n, "alarmName": name, "alarmLevel": level,
            "targetDeviceId": target, "occurredAt": "2026-11-05T09:00:00+09:00", "status": status}


def write_alarms(path, alarms):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"alarms": alarms}, f, ensure_ascii=False)


def embedded(html):
    m = re.search(r'<script id="viz-data" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


def run_main(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = visualizer.main(args)
    return code, out.getvalue(), err.getvalue()


STUB_JS = r"""
function El(tag) {
  this.tagName = tag; this.attrs = {}; this.children = []; this.listeners = {}; this.style = {};
  this.textContent = ''; this.className = ''; this.open = false; this.disabled = false; this.parent = null;
  this.namespaceURI = 'http://www.w3.org/2000/svg';
}
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.getAttribute = function (k) { return this.attrs[k]; };
El.prototype.appendChild = function (c) { c.parent = this; this.children.push(c); return c; };
El.prototype.removeChild = function (c) { this.children.splice(this.children.indexOf(c), 1); };
Object.defineProperty(El.prototype, 'firstChild', {get: function () { return this.children[0] || null; }});
El.prototype.addEventListener = function (t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); };
El.prototype.click = function () { (this.listeners.click || []).forEach(function (f) { f({}); }); };
var BYID = {};
['viz-data', 'chips', 'notes', 'graph', 'edges', 'nodes', 'detail'].forEach(function (id) { BYID[id] = new El('div'); });
BYID['viz-data'].textContent = JSON.stringify(__JSON__);
BYID.graph.createSVGPoint = function () { return {x: 0, y: 0, matrixTransform: function () { return {x: 0, y: 0}; }}; };
var document = {
  getElementById: function (id) { return BYID[id]; },
  createElementNS: function (ns, t) { return new El(t); },
  createElement: function (t) { return new El(t); }
};
var window = {addEventListener: function () {}, removeEventListener: function () {}};
"""

CLICK_JS = r"""
function chipOf(key) {
  var found = BYID.chips.children.filter(function (c) { return c.attrs['data-chip'] === key; });
  if (found.length !== 1) { throw new Error('chip not found: ' + key); }
  return found[0];
}
function assert(c, m) { if (!c) { throw new Error('assert: ' + m); } }
var paths = BYID.edges.children;
var nodes = BYID.nodes.children.filter(function (g) { return g.tagName === 'g'; });
assert(paths.length === 4, 'edges ' + paths.length);
assert(nodes.length === 4, 'nodes ' + nodes.length);
assert(chipOf('physical').tagName === 'button', 'button');
var vbBefore = BYID.graph.attrs.viewBox;

chipOf('physical').click();
var phys = paths.filter(function (p) { return !p.attrs['stroke-dasharray']; });
var lsp = paths.filter(function (p) { return p.attrs['stroke-dasharray']; });
assert(phys.length === 2 && lsp.length === 2, 'kinds');
assert(phys.every(function (p) { return p.style.display === 'none'; }), 'physical hidden');
assert(lsp.every(function (p) { return p.style.display === ''; }), 'lsp shown');
chipOf('physical').click();
assert(phys.every(function (p) { return p.style.display === ''; }), 'physical shown again');

chipOf('lsp').click();
assert(lsp.every(function (p) { return p.style.display === 'none'; }), 'lsp hidden');
chipOf('lsp').click();

chipOf('alarm').click();
assert(chipOf('alarm').attrs['aria-pressed'] === 'true', 'alarm pressed');
var dimmed = nodes.filter(function (g) { return g.style.opacity === '0.15'; });
assert(dimmed.length === 2, 'dimmed ' + dimmed.length);   // アラーム装置は2つ(A, C)
chipOf('alarm').click();
assert(nodes.every(function (g) { return g.style.opacity === ''; }), 'alarm released');

chipOf('isolated').click();
dimmed = nodes.filter(function (g) { return g.style.opacity === '0.15'; });
assert(dimmed.length === 3, 'isolated dimmed ' + dimmed.length);   // 接続なしは1つ(D)、他の3つが薄くなる
chipOf('physical').click();
chipOf('devices').click();   // 全体表示に戻す: フィルタ・強調を解除
assert(nodes.every(function (g) { return g.style.opacity === ''; }), 'reset nodes');
assert(paths.every(function (p) { return p.style.display === ''; }), 'reset edges');
assert(BYID.graph.attrs.viewBox === vbBefore, 'reset view');

var det = BYID.notes.children.filter(function (c) { return c.className === 'warn'; })[0];
assert(det && det.open === true, 'warn open');
chipOf('warnings').click();
assert(det.open === false, 'warn closed');
chipOf('warnings').click();
assert(det.open === true, 'warn reopened');
console.log('OK');
"""


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)


class LoaderTest(TempDirCase):
    def test_load_noim_and_alarms(self):  # FR1.1、FR1.2
        write_noim(self.tmp, sample_noim())
        noim = load_noim(self.tmp)
        self.assertEqual([p["commonName"] for p in noim["pds"]], [u"装置A", u"装置B", u"装置C", u"装置D"])
        self.assertEqual(len(noim["pls"]), 5)
        write_alarms(self.path("a.json"), [alarm(1, u"温度異常", 3, "active", u"装置A")])
        self.assertEqual(load_alarms(self.path("a.json"))[0]["alarmLevel"], 3)

    def test_missing_csv_names_file(self):  # FR1.3
        write_noim(self.tmp, sample_noim())
        os.remove(self.path(file_name("pls")))
        with self.assertRaises(VizError) as cm:
            load_noim(self.tmp)
        self.assertIn("resourceInfo_pls.csv", str(cm.exception))

    def test_broken_alarm_json(self):  # FR1.3
        with open(self.path("a.json"), "w", encoding="utf-8") as f:
            f.write("{ broken")
        with self.assertRaises(VizError) as cm:
            load_alarms(self.path("a.json"))
        self.assertIn("a.json", str(cm.exception))

    def test_invalid_alarms_rejected(self):  # FR1.2、FR1.3
        good = alarm(1, u"x", 2, "active", u"装置A")
        missing = dict(good)
        del missing["occurredAt"]
        cases = [("occurredAt", [missing]),
                 ("alarmLevel", [dict(good, alarmLevel=4)]),
                 ("alarmLevel", [dict(good, alarmLevel=True)]),
                 ("status", [dict(good, status="unknown")]),
                 ("alarmId", [good, dict(good)])]
        for word, alarms in cases:
            write_alarms(self.path("a.json"), alarms)
            with self.assertRaises(VizError) as cm:
                load_alarms(self.path("a.json"))
            self.assertIn(word, str(cm.exception))


class GraphTest(unittest.TestCase):
    def setUp(self):
        self.g = build_graph(sample_noim(), [
            alarm(1, u"温度異常", 3, "active", u"装置A"),
            alarm(2, u"通信断", 2, "active", u"装置A"),
            alarm(3, u"復旧", 1, "recovered", u"装置B"),
            alarm(4, u"不明", 2, "active", u"存在しない装置"),
        ])

    def edges(self, kind):
        names = dict((d["id"], d["name"]) for d in self.g["devices"])
        return dict(((names[e["source"]], names[e["target"]]), e) for e in self.g["edges"] if e["kind"] == kind)

    def test_devices(self):  # FR2.1
        d = self.g["devices"][0]
        self.assertEqual((d["id"], d["name"], d["type"]), ("node1", u"装置A", "CER1"))
        self.assertEqual(len(self.g["devices"]), 4)

    def test_physical_edges_merged(self):  # FR2.2、FR2.5
        e = self.edges("physical")
        self.assertEqual(sorted(e), [(u"装置A", u"装置B"), (u"装置B", u"装置C")])
        self.assertEqual(e[(u"装置A", u"装置B")]["count"], 2)
        self.assertEqual(e[(u"装置A", u"装置B")]["names"], ["link1", "link2"])

    def test_lsp_edges(self):  # FR2.3
        self.assertEqual(sorted(self.edges("lsp")), [(u"装置A", u"装置B"), (u"装置B", u"装置C")])

    def test_undrawable_connections_warn(self):  # FR2.4
        text = "\n".join(self.g["warnings"])
        self.assertEqual(len(self.g["warnings"]), 3)
        self.assertIn("link4", text)
        self.assertIn("link5", text)
        self.assertIn("nc3", text)
        self.assertEqual(self.g["summary"]["warnings"], 3)

    def test_alarm_matching(self):  # FR3.1、FR3.2
        by_name = dict((d["name"], d) for d in self.g["devices"])
        self.assertEqual(by_name[u"装置A"]["severity"], 3)
        self.assertEqual(len(by_name[u"装置A"]["alarms"]), 2)
        self.assertEqual(by_name[u"装置B"]["severity"], 0)  # recovered のみは強調しない
        self.assertEqual(len(by_name[u"装置B"]["alarms"]), 1)
        self.assertEqual([a["alarmId"] for a in self.g["unmatched_alarms"]], ["ALM-00004"])
        s = self.g["summary"]
        self.assertEqual((s["alarm_devices"], s["active_alarms"], s["recovered_alarms"], s["unmatched_alarms"]),
                         (1, 3, 1, 1))

    def test_duplicate_device_name_is_error(self):  # 前提 A2
        noim = sample_noim()
        noim["pds"][1]["commonName"] = u"装置A"
        with self.assertRaises(VizError) as cm:
            build_graph(noim, [])
        self.assertIn(u"装置A", str(cm.exception))

    def test_credentials_not_in_graph(self):  # FR5.1
        self.assertNotIn(SECRET, json.dumps(self.g, ensure_ascii=False))


class LayoutTest(unittest.TestCase):
    def test_deterministic_and_in_bounds(self):  # FR6.2
        g = build_graph(sample_noim(), [])
        ids = [d["id"] for d in g["devices"]]
        a = compute_layout(ids, g["edges"])
        self.assertEqual(a, compute_layout(ids, g["edges"]))
        self.assertEqual(sorted(a), sorted(ids))
        for x, y in a.values():
            self.assertTrue(0 <= x <= WIDTH and 0 <= y <= HEIGHT)
        self.assertEqual(compute_layout([], []), {})

    def assert_no_label_overlap(self, devices, pos):
        """全ての組で、ラベルの幅の目安より横に離れているか、縦に離れている(=ラベルが重ならない)。"""
        for i, a in enumerate(devices):
            for b in devices[i + 1:]:
                (ax, ay), (bx, by) = pos[a["id"]], pos[b["id"]]
                half = (label_width(short_label(a["name"])) + label_width(short_label(b["name"]))) / 2
                self.assertTrue(abs(ax - bx) >= half or abs(ay - by) >= NODE_BOX_H,
                                "ラベルが重なる: %s / %s" % (a["name"], b["name"]))

    def test_labels_do_not_overlap_sample(self):  # 修正(a)
        g = build_graph(sample_noim(), [])
        self.assert_no_label_overlap(g["devices"], layout_graph(g))

    def test_labels_do_not_overlap_crowded(self):  # 修正(a): 長い名前の装置を多数、全部つなげても重ならない
        noim = {"pds": [pd(n, u"関西・とても長い装置の名前%02d" % n) for n in range(1, 31)], "pPorts": [], "pls": [], "fres": []}
        for n in range(1, 31):
            noim["pPorts"].append(pport(n, n))
        for n in range(1, 30):
            noim["pls"].append(plink(n, [n, n + 1]))
        g = build_graph(noim, [])
        pos = layout_graph(g)
        self.assertEqual(pos, layout_graph(g))  # 決定的
        self.assert_no_label_overlap(g["devices"], pos)

    def test_labels_do_not_overlap_real_data(self):  # 修正(a): 実データの26装置
        if not os.path.isdir(REAL_NOIM):
            self.skipTest("noim_output_sample がありません")
        g = build_graph(load_noim(REAL_NOIM), [])
        self.assertEqual(len(g["devices"]), 26)
        self.assert_no_label_overlap(g["devices"], layout_graph(g))

    def test_isolated_devices_are_grouped_on_the_left(self):  # 修正(c)
        g = build_graph(sample_noim(), [])
        by_name = dict((d["name"], d) for d in g["devices"])
        self.assertTrue(by_name[u"装置D"]["isolated"])
        self.assertFalse(by_name[u"装置A"]["isolated"])
        self.assertEqual(g["summary"]["isolated_devices"], 1)
        pos = layout_graph(g)
        iso_x = pos[by_name[u"装置D"]["id"]][0]
        for n in (u"装置A", u"装置B", u"装置C"):
            self.assertLess(iso_x, pos[by_name[n]["id"]][0])


class HtmlTest(unittest.TestCase):
    def make(self, noim=None, alarms=None):
        g = build_graph(noim or sample_noim(), alarms if alarms is not None else [
            alarm(1, u"温度異常", 3, "active", u"装置A"),
            alarm(2, u"通信断", 2, "active", u"装置C"),
            alarm(3, u"復旧", 1, "recovered", u"装置B"),
            alarm(4, u"不明", 2, "active", u"存在しない装置"),
        ])
        return render_html(g, compute_layout([d["id"] for d in g["devices"]], g["edges"]))

    def test_self_contained(self):  # FR4.1、NFR1
        html = self.make()
        for bad in ("http://", "https://", "//cdn", "src=", "<link", "@import", "url("):
            self.assertNotIn(bad, html)

    def test_colors_and_summary_data(self):  # FR4.2〜FR4.4
        data = embedded(self.make())
        sev = dict((d["name"], d["severity"]) for d in data["devices"])
        self.assertEqual(sev, {u"装置A": 3, u"装置B": 0, u"装置C": 2, u"装置D": 0})
        s = data["summary"]
        self.assertEqual((s["devices"], s["physical_edges"], s["lsp_edges"], s["alarm_devices"]), (4, 2, 2, 2))
        self.assertEqual(s["unmatched_alarms"], 1)
        self.assertEqual(len(data["warnings"]), 3)
        self.assertEqual([a["alarmId"] for a in data["unmatched"]], ["ALM-00004"])
        recovered = [a for d in data["devices"] for a in d["alarms"] if a["status"] == "recovered"]
        self.assertEqual(len(recovered), 1)  # 詳細パネルの一覧に載る(薄い表示はJS側)
        html = self.make()
        for color in ("#f2c200", "#f28c00", "#d62728"):
            self.assertIn(color, html)

    def test_deterministic(self):  # FR6.2
        self.assertEqual(self.make(), self.make())

    def test_escaping(self):  # FR4.1
        noim = sample_noim()
        noim["pds"][0]["commonName"] = u"</script><b>&装置"
        html = self.make(noim, [])
        self.assertEqual(html.count("</script>"), 2)  # 本物の閉じタグ(データ用とJS用)だけ
        self.assertEqual(embedded(html)["devices"][0]["name"], u"</script><b>&装置")

    def test_credentials_not_in_html(self):  # FR5.1
        self.assertNotIn(SECRET, self.make())

    def test_chips_are_buttons_with_handlers(self):  # 修正(b)
        html = self.make()
        self.assertIn("h('button'", html)
        self.assertIn("cursor: pointer", html)
        self.assertIn("aria-pressed", html)
        for key in ("devices", "physical", "lsp", "isolated", "alarm", "warnings"):
            self.assertIn("chip('%s'" % key, html)
        for fn in ("function resetAll", "function toggleKind", "function toggleFocus", "function toggleDetails"):
            self.assertIn(fn, html)

    def test_isolated_in_summary_and_payload(self):  # 修正(c)
        data = embedded(self.make())
        self.assertEqual(data["summary"]["isolated_devices"], 1)
        iso = dict((d["name"], d["isolated"]) for d in data["devices"])
        self.assertEqual(iso, {u"装置A": False, u"装置B": False, u"装置C": False, u"装置D": True})
        self.assertEqual(data["isolated_title"]["count"], 1)
        self.assertIn(u"接続なし", self.make())

    def test_chip_clicks_with_node_stub(self):  # 修正(b): Node があれば、簡易スタブでクリックを呼ぶ
        node = shutil.which("node")
        if not node:
            self.skipTest("node がありません")
        html = self.make()
        script = re.findall(r"<script>(.*?)</script>", html, re.S)[0]
        driver = STUB_JS + "\n" + script + "\n" + CLICK_JS
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "stub.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(driver.replace("__JSON__", json.dumps(embedded(html))))
        res = subprocess.run([node, path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr.decode("utf-8", "replace"))
        self.assertIn("OK", res.stdout.decode("utf-8"))


class CliAndRealDataTest(TempDirCase):
    def test_exit_codes(self):  # FR6.1、FR6.3
        write_noim(self.tmp, sample_noim())
        write_alarms(self.path("a.json"), [alarm(1, u"温度異常", 3, "active", u"装置A")])
        html = self.path("out.html")

        code, out, err = run_main([self.tmp])  # 引数不足
        self.assertEqual(code, 2)

        code, out, err = run_main([self.tmp, self.path("nothing.json"), html])  # アラームJSONなし
        self.assertEqual(code, 1)
        self.assertIn("エラー:", err)
        self.assertFalse(os.path.exists(html))

        code, out, err = run_main([self.tmp, self.path("a.json"), html])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(html))
        self.assertIn("警告", out)  # 描けない接続の警告が標準出力にも出る

    def test_real_data_end_to_end(self):  # FR3.3、FR2、FR5.1(読み取りだけ: 変換は一時ディレクトリ内)
        inp = self.path("in")
        os.makedirs(inp)
        for name in os.listdir(REAL_INPUT):
            src = os.path.join(REAL_INPUT, name)
            dst = os.path.join(inp, name)
            if name.startswith("t_mst_vxm_node_info_"):
                with open(src, "r", encoding="utf-8-sig", newline="") as f:
                    reader = csv.DictReader(f)
                    fields, rows = reader.fieldnames, list(reader)
                for r in rows:
                    r["password"] = SECRET
                with open(dst, "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.DictWriter(f, fields, lineterminator="\r\n")
                    w.writeheader()
                    w.writerows(rows)
            elif os.path.isfile(src):
                shutil.copy(src, dst)
        noim_dir = self.path("noim")
        noim_converter.run(inp, noim_dir, out=io.StringIO())
        with open(os.path.join(noim_dir, file_name("pds")), encoding="utf-8") as f:
            self.assertIn(SECRET, f.read())  # 出力CSVには入っている(このテストの前提)

        html_path = self.path("out.html")
        code, out, err = run_main([noim_dir, REAL_ALARMS, html_path])
        self.assertEqual(code, 0, err)
        with open(html_path, encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn(SECRET, html)
        data = embedded(html)
        self.assertEqual(data["summary"]["devices"], 26)
        sev = dict((d["name"], d["severity"]) for d in data["devices"])
        self.assertEqual(sev[u"関西・アバンザCER1-A"], 3)
        self.assertEqual(sev[u"関西・COM京都南RR2-A"], 2)
        self.assertEqual(sev[u"アバンザSAS2-01-A_アバンザCER1-A01"], 1)
        self.assertEqual(sev[u"関西・谷町ビルCER1-B"], 0)  # recovered のみ
        self.assertEqual(data["summary"]["unmatched_alarms"], 0)
        # 接続なし: PD 26 のうち CE 12 台は物理接続・LSP接続の端にならない(NOIM出力に接続リソースが無い)
        isolated = sorted(d["name"] for d in data["devices"] if d["isolated"])
        self.assertEqual(data["summary"]["isolated_devices"], 12)
        self.assertEqual(len(isolated), 12)
        self.assertTrue(all(d["type"] == "CE" for d in data["devices"] if d["isolated"]))
        # 描けた物理接続の本数 + 警告で除いた本数 = PLinkの件数(警告があれば件数が出ている)
        drawn = sum(e["count"] for e in data["edges"] if e["kind"] == "physical")
        total = len(load_noim(noim_dir)["pls"])
        self.assertTrue(drawn == total or data["warnings"])


if __name__ == "__main__":
    unittest.main()
