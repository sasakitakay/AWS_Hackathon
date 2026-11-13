"""出力CSV・全体の流れ・コマンドラインのテスト(FR3、FR4、FR5)。入出力は一時ディレクトリで行う。"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

import noim_converter
from noim.converters import RESOURCE_KINDS
from noim.errors import ToolError
from noim.output_csv import file_name, to_csv_bytes, write_outputs
from tests.test_input import make_input_dir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_INPUT = os.path.join(ROOT, u"入力ファイル")

REF_KEYS = (
    "_tpeIdRef", "_physicalPort", "_aEndTpeRefList", "_zEndTpeRefList", "_physicalPortRefList",
    "nttServerTpeRefList", "_edgeTpeRefList", "_supportingFreRefList", "nttServerConnectionRefList",
    "nttPhysicalStructure",
)


def run_main(args):
    """main を呼び、(終了ステータス, 標準出力, 標準エラー) を返す。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = noim_converter.main(args)
    return code, out.getvalue(), err.getvalue()


def empty_result():
    return dict((k, []) for k in RESOURCE_KINDS)


class CsvFormatTest(unittest.TestCase):
    def test_header_quotes_crlf_and_escape(self):
        res = {"objectId": "http://localhost:3000/tpes/system_00000001",
               "commonName": u'名前"引用"\\と\n改行', "list": ["a"], "none": None}
        data = to_csv_bytes([res])
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))  # BOMなし
        text = data.decode("utf-8")
        lines = text.split("\r\n")
        self.assertEqual(lines[0], '"objectId","data"')
        self.assertEqual(lines[-1], "")  # 末尾もCRLF
        self.assertEqual(len(lines), 3)  # 改行はJSONの \n にエスケープされ、フィールド内に生の改行はない
        row = lines[1]
        self.assertTrue(row.startswith('"http://localhost:3000/tpes/system_00000001","{'))
        self.assertTrue(row.endswith('}"'))
        # CSVの " は "" でエスケープされ、読み戻すとJSONとして元の内容になる
        import csv
        parsed = list(csv.reader(io.StringIO(text, newline="")))
        self.assertEqual(parsed[0], ["objectId", "data"])
        self.assertEqual(parsed[1][0], res["objectId"])
        self.assertEqual(json.loads(parsed[1][1]), res)
        self.assertIn(u"名前", parsed[1][1])  # 日本語はエスケープしない

    def test_empty_resource_list_has_header_only(self):
        self.assertEqual(to_csv_bytes([]), b'"objectId","data"\r\n')


class WriteOutputsTest(unittest.TestCase):
    def sample(self):
        result = empty_result()
        for i, kind in enumerate(RESOURCE_KINDS):
            result[kind] = [{"objectId": "http://localhost:3000/%s/system_%08d" % (kind, i + 1), "n": i}]
        return result

    def test_creates_dir_and_writes_eight_files_then_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "a", "b")  # 存在しない出力ディレクトリは作る
            paths = write_outputs(self.sample(), out)
            self.assertEqual([os.path.basename(p) for p in paths], [file_name(k) for k in RESOURCE_KINDS])
            self.assertEqual(sorted(os.listdir(out)), sorted(file_name(k) for k in RESOURCE_KINDS))
            self.assertEqual(len(paths), 8)
            # 同名ファイルは上書き、一時ファイルは残らない
            result = self.sample()
            result["tls"] = []
            write_outputs(result, out)
            with open(os.path.join(out, file_name("tls")), "rb") as f:
                self.assertEqual(f.read(), b'"objectId","data"\r\n')
            self.assertEqual(len(os.listdir(out)), 8)

    def test_write_failure_keeps_written_files_and_removes_tmp(self):
        with tempfile.TemporaryDirectory() as d:
            # 4番目のファイルと同名のディレクトリがあるため、そこで置き換えに失敗する
            os.mkdir(os.path.join(d, file_name(RESOURCE_KINDS[3])))
            with self.assertRaises(ToolError) as cm:
                write_outputs(self.sample(), d)
            self.assertIn(file_name(RESOURCE_KINDS[3]), str(cm.exception))
            names = os.listdir(d)
            for kind in RESOURCE_KINDS[:3]:
                self.assertIn(file_name(kind), names)  # 書き出し済みは残す
            self.assertFalse([n for n in names if n.endswith(".tmp")])
            self.assertNotIn(file_name(RESOURCE_KINDS[4]), names)  # 失敗以降は書かない

    def test_output_path_is_a_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "afile")
            open(path, "w").close()
            with self.assertRaises(ToolError):
                write_outputs(self.sample(), path)


class MainTest(unittest.TestCase):
    def test_success_and_exit_status(self):
        with tempfile.TemporaryDirectory() as d:
            make_input_dir(os.path.join(d))
            out = os.path.join(d, "out")
            code, stdout, stderr = run_main([d, out])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(len(os.listdir(out)), 8)
            self.assertIn(out, stdout)
            self.assertEqual(stderr, "")

    def test_argument_errors_exit_2(self):
        for args in ([], ["only_input"], ["a", "b", "--unknown"]):
            code, _o, _e = run_main(args)
            self.assertEqual(code, 2, args)

    def test_input_error_exit_1_and_nothing_written(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out")
            code, stdout, stderr = run_main([os.path.join(d, "missing"), out])
            self.assertEqual(code, 1)
            self.assertIn("missing", stderr)
            self.assertFalse(os.path.exists(out))  # 読み込み・変換に失敗したら出力は書かない

    def test_conversion_error_exit_1_names_service(self):
        with tempfile.TemporaryDirectory() as d:
            make_input_dir(d)
            # 物理(BR)なのに client_entity_id_list が1件だけのサービスにして、変換エラーにする
            from noim.input_csv import SERVICE_COLUMNS
            from tests.test_input import csv_text, write
            write(os.path.join(d, "t_mst_vxm_service_202508051943.csv"),
                  csv_text(SERVICE_COLUMNS, [{"name": u"壊れた線", "service_profile_name": u"物理(BR)",
                                              "client_entity_id_list": "{e1}"}]))
            out = os.path.join(d, "out")
            code, _o, stderr = run_main([d, out])
            self.assertEqual(code, 1)
            self.assertIn(u"壊れた線", stderr)
            self.assertFalse(os.path.exists(out))

    def test_expected_match_mismatch_and_not_given(self):
        with tempfile.TemporaryDirectory() as d:
            inp = os.path.join(d, "in")
            os.mkdir(inp)
            make_input_dir(inp)
            out = os.path.join(d, "out")
            self.assertEqual(run_main([inp, out])[0], 0)  # 未指定: 比較しない
            # 期待結果 = 出力のコピー: 一致して0
            exp = os.path.join(d, "exp")
            os.mkdir(exp)
            for name in os.listdir(out):
                with open(os.path.join(out, name), "rb") as f:
                    data = f.read()
                with open(os.path.join(exp, name), "wb") as f:
                    f.write(data)
            code, stdout, _e = run_main([inp, out, "--expected", exp])
            self.assertEqual(code, 0)
            self.assertIn(u"完全に一致", stdout)
            # 1ファイルを書き換える: 不一致で1、差分が読める形で表示される
            target = os.path.join(exp, file_name("pds"))
            with open(target, "rb") as f:
                data = f.read()
            with open(target, "wb") as f:
                f.write(data.replace(u"ノード1".encode("utf-8"), u"ノード2".encode("utf-8")))
            code, _o, stderr = run_main([inp, out, "--expected", exp])
            self.assertEqual(code, 1)
            self.assertIn(file_name("pds"), stderr)
            self.assertIn(u"ノード2", stderr)
            self.assertIn(u"ノード1", stderr)
            # UTF-8として読めない期待結果: 最初の差異位置を表示
            with open(target, "wb") as f:
                f.write(b"\xff\xfe\x00")
            code, _o, stderr = run_main([inp, out, "--expected", exp])
            self.assertEqual(code, 1)
            self.assertIn(u"バイト位置 0", stderr)
            # 期待結果ファイルがない / 期待結果ディレクトリがない
            os.remove(target)
            code, _o, stderr = run_main([inp, out, "--expected", exp])
            self.assertEqual(code, 1)
            self.assertIn(file_name("pds"), stderr)
            code, _o, stderr = run_main([inp, out, "--expected", os.path.join(d, "nodir")])
            self.assertEqual(code, 1)


class RealDataTest(unittest.TestCase):
    """入力ファイル/ の実データで通し実行する(FR5.1)。入力は読み取りのみ。"""

    def test_end_to_end_via_command_line(self):
        with tempfile.TemporaryDirectory() as d:
            proc = subprocess.run(
                [sys.executable, os.path.join(ROOT, "noim_converter.py"), REAL_INPUT, d],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
            self.assertEqual(sorted(os.listdir(d)), sorted(file_name(k) for k in RESOURCE_KINDS))

            all_ids = set()
            resources = []
            for kind in RESOURCE_KINDS:
                with open(os.path.join(d, file_name(kind)), "rb") as f:
                    raw = f.read()
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), kind)
                text = raw.decode("utf-8")
                self.assertTrue(text.startswith('"objectId","data"\r\n'), kind)
                self.assertTrue(text.endswith("\r\n"), kind)
                body = text.split("\r\n")[1:-1]
                self.assertNotIn("\n", "".join(body).replace("\\n", ""))  # 生の改行はCRLFだけ
                import csv
                rows = list(csv.reader(io.StringIO(text, newline="")))
                self.assertEqual(rows[0], ["objectId", "data"])
                for line, row in zip(body, rows[1:]):
                    self.assertTrue(line.startswith('"') and line.endswith('"'), kind)  # 全項目クォート
                    self.assertEqual(len(row), 2)
                    data = json.loads(row[1])  # dataはJSONとして読める
                    self.assertEqual(data["objectId"], row[0])
                    self.assertNotIn(row[0], all_ids)  # objectIdの重複なし
                    all_ids.add(row[0])
                    resources.append(data)
                self.assertEqual(len(rows) - 1, len(body))

            # リソース間で参照しているobjectIdは、すべて出力内に存在する
            missing = []

            def walk(node, owner):
                if isinstance(node, dict):
                    for key, value in node.items():
                        if key in REF_KEYS:
                            for ref in (value if isinstance(value, list) else [value]):
                                if isinstance(ref, dict):
                                    ref = ref.get(key)
                                if ref not in all_ids:
                                    missing.append((owner, key, ref))
                        walk(value, owner)
                elif isinstance(node, list):
                    for item in node:
                        walk(item, owner)

            for res in resources:
                walk(res, res["objectId"])
            self.assertEqual(missing, [])

            counts = {}
            for kind in RESOURCE_KINDS:
                with open(os.path.join(d, file_name(kind)), "rb") as f:
                    counts[kind] = f.read().count(b"\r\n") - 1
            self.assertTrue(all(counts[k] > 0 for k in RESOURCE_KINDS), counts)


if __name__ == "__main__":
    unittest.main()
