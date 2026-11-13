"""入力CSVの選択・読み込みと、objectId採番のテスト(FR1、NFR)。"""

import os
import tempfile
import unittest

from noim.errors import ToolError
from noim.input_csv import (
    ENTITY_COLUMNS, NODE_COLUMNS, SERVICE_COLUMNS, load_inputs, parse_pg_array, read_rows,
    select_input_files,
)
from noim.object_id import ObjectIdManager


def write(path, text, bom=True):
    with open(path, "wb") as f:
        f.write((u"\ufeff" if bom else u"").encode("utf-8") + text.encode("utf-8"))


def csv_text(columns, rows):
    """columns の列を持つ CSV 文字列。rows は {列名: 値} の辞書のリスト(省略した列は空)。"""
    lines = [",".join(columns)]
    for r in rows:
        lines.append(",".join(_q(r.get(c, "")) for c in columns))
    return "\r\n".join(lines) + "\r\n"


def _q(v):
    if any(ch in v for ch in ',"\r\n'):
        return '"' + v.replace('"', '""') + '"'
    return v


def make_input_dir(d, stamp="202508051943"):
    write(os.path.join(d, "t_mst_vxm_node_info_%s.csv" % stamp),
          csv_text(NODE_COLUMNS, [{"ra_vxm_id": "n1", "name": "ノード1", "scope_id_list": "{a,b}"}]))
    write(os.path.join(d, "t_mst_vxm_entity_info_%s.csv" % stamp),
          csv_text(ENTITY_COLUMNS, [{"ra_vxm_id": "e1", "name": "ポート1", "node_id": "n1"}]))
    write(os.path.join(d, "t_mst_vxm_service_%s.csv" % stamp),
          csv_text(SERVICE_COLUMNS, [{"ra_vxm_id": "s1", "name": "サービス1",
                                      "client_entity_id_list": '{"e 1",e2}'}]))


class ParsePgArrayTest(unittest.TestCase):
    def test_empty_and_plain(self):
        self.assertEqual(parse_pg_array(""), [])
        self.assertEqual(parse_pg_array("{}"), [])
        self.assertEqual(parse_pg_array("{a,b,c}"), ["a", "b", "c"])

    def test_quoted(self):
        self.assertEqual(parse_pg_array('{"x y","z"}'), ["x y", "z"])
        self.assertEqual(parse_pg_array('{"a,b","c\\"d"}'), ["a,b", 'c"d'])

    def test_invalid(self):
        for bad in ("abc", "{a,b", '{"a}', "{a,}"):
            with self.assertRaises(ValueError):
                parse_pg_array(bad)


class SelectInputFilesTest(unittest.TestCase):
    def test_select_latest_per_kind(self):
        with tempfile.TemporaryDirectory() as d:
            make_input_dir(d, "202508051943")
            make_input_dir(d, "202508061200")
            make_input_dir(d, "202507010000")
            files = select_input_files(d)
            self.assertEqual(set(files), {"node", "entity", "service"})
            self.assertTrue(files["node"].endswith("t_mst_vxm_node_info_202508061200.csv"))
            self.assertTrue(files["entity"].endswith("t_mst_vxm_entity_info_202508061200.csv"))
            self.assertTrue(files["service"].endswith("t_mst_vxm_service_202508061200.csv"))

    def test_subdirectory_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            make_input_dir(d)
            os.makedirs(os.path.join(d, "sub"))
            write(os.path.join(d, "sub", "unknown.txt"), "x")
            self.assertEqual(len(select_input_files(d)), 3)

    def test_unknown_file_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            make_input_dir(d)
            write(os.path.join(d, "memo.txt"), "x")
            with self.assertRaises(ToolError) as cm:
                select_input_files(d)
            self.assertIn("memo.txt", str(cm.exception))

    def test_missing_kind_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            make_input_dir(d)
            os.remove(os.path.join(d, "t_mst_vxm_service_202508051943.csv"))
            with self.assertRaises(ToolError) as cm:
                select_input_files(d)
            self.assertIn("service", str(cm.exception))

    def test_dir_missing_or_not_directory(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ToolError) as cm:
                select_input_files(os.path.join(d, "none"))
            self.assertIn("存在しません", str(cm.exception))
            f = os.path.join(d, "file.txt")
            write(f, "x")
            with self.assertRaises(ToolError) as cm:
                select_input_files(f)
            self.assertIn("ディレクトリではありません", str(cm.exception))


class ReadRowsTest(unittest.TestCase):
    def test_load_inputs_values(self):
        with tempfile.TemporaryDirectory() as d:
            make_input_dir(d)
            nodes, entities, services = load_inputs(d)
            self.assertEqual(len(nodes), 1)
            self.assertEqual(nodes[0]["name"], "ノード1")  # BOMが取り除かれ、先頭列名も正しい
            self.assertEqual(nodes[0]["ra_vxm_id"], "n1")
            self.assertEqual(nodes[0]["scope_id_list"], ["a", "b"])
            self.assertEqual(nodes[0]["scope_name_list"], [])
            self.assertEqual(nodes[0]["memo"], "")
            self.assertEqual(entities[0]["node_id"], "n1")
            self.assertEqual(services[0]["client_entity_id_list"], ["e 1", "e2"])
            self.assertEqual(services[0].line, 2)

    def test_missing_column(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t_mst_vxm_entity_info_202508051943.csv")
            write(p, "ra_vxm_id,name\r\ne1,x\r\n")
            with self.assertRaises(ToolError) as cm:
                read_rows(p, "entity")
            msg = str(cm.exception)
            self.assertIn("t_mst_vxm_entity_info_202508051943.csv", msg)
            self.assertIn("node_id", msg)

    def test_bad_array_reports_file_line_column(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t_mst_vxm_service_202508051943.csv")
            write(p, csv_text(SERVICE_COLUMNS, [{"client_entity_id_list": "{a,b"}]))
            with self.assertRaises(ToolError) as cm:
                read_rows(p, "service")
            msg = str(cm.exception)
            self.assertIn("行 2", msg)
            self.assertIn("client_entity_id_list", msg)

    def test_wrong_field_count(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t_mst_vxm_entity_info_202508051943.csv")
            write(p, ",".join(ENTITY_COLUMNS) + "\r\na,b\r\n")
            with self.assertRaises(ToolError) as cm:
                read_rows(p, "entity")
            self.assertIn("行 2", str(cm.exception))

    def test_not_utf8_and_unreadable(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t_mst_vxm_entity_info_202508051943.csv")
            with open(p, "wb") as f:
                f.write(b"\xff\xfe\x00bad")
            with self.assertRaises(ToolError):
                read_rows(p, "entity")
            with self.assertRaises(ToolError):
                read_rows(os.path.join(d, "none.csv"), "entity")


class ObjectIdTest(unittest.TestCase):
    def test_numbering_per_kind_decimal_8_digits(self):
        m = ObjectIdManager()
        self.assertEqual(m.next_id("pds"), "http://localhost:3000/pds/system_00000001")
        self.assertEqual(m.next_id("pds"), "http://localhost:3000/pds/system_00000002")
        self.assertEqual(m.next_id("tpes"), "http://localhost:3000/tpes/system_00000001")
        for _ in range(8):
            m.next_id("tpes")
        self.assertEqual(m.next_id("tpes"), "http://localhost:3000/tpes/system_00000010")

    def test_new_manager_restarts_from_one(self):
        ObjectIdManager().next_id("fres")
        self.assertEqual(ObjectIdManager().next_id("fres"), "http://localhost:3000/fres/system_00000001")

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            ObjectIdManager().next_id("unknown")


if __name__ == "__main__":
    unittest.main()
