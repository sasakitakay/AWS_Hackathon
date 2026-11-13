#!/usr/bin/env python3
"""NOIM変換ツール(PoC)。

3つの入力CSV(ノード/エンティティ/サービス)を詳細設計書どおりにNOIM形式へ変換し、
出力ディレクトリに resourceInfo_*.csv(8ファイル)を書き出す。

使い方:
    python noim_converter.py <入力ディレクトリ> <出力ディレクトリ> [--expected <期待結果ディレクトリ>]

終了ステータス: 0 成功 / 1 読み込み・変換・書き込み・比較の失敗 / 2 引数エラー
"""

import argparse
import difflib
import os
import sys

from noim.converters import convert_all
from noim.errors import ToolError
from noim.input_csv import load_inputs
from noim.output_csv import write_outputs

MAX_DIFF_LINES = 40


def run(input_dir, output_dir, expected_dir=None, out=None):
    """読み込み -> 変換(メモリ上) -> 書き出し -> (指定時のみ)期待結果との比較。失敗は ToolError。"""
    out = out or sys.stdout
    nodes, entities, services = load_inputs(input_dir)
    result = convert_all(nodes, entities, services)
    paths = write_outputs(result, output_dir)
    out.write("変換が完了しました: %d ファイルを %s に書き出しました\n" % (len(paths), output_dir))
    for path in paths:
        out.write("  %s\n" % os.path.basename(path))
    if expected_dir is not None:
        compare_with_expected(paths, expected_dir, out)
    return paths


def _describe_diff(actual, expected):
    """差異を読める形の文字列にする。UTF-8として読めれば行の差分、読めなければ最初の差異位置。"""
    try:
        a_lines = actual.decode("utf-8").splitlines(True)
        e_lines = expected.decode("utf-8").splitlines(True)
    except UnicodeDecodeError:
        n = min(len(actual), len(expected))
        pos = next((i for i in range(n) if actual[i] != expected[i]), n)
        return "最初の差異はバイト位置 %d です (出力 %d バイト / 期待 %d バイト)" % (pos, len(actual), len(expected))
    diff = list(difflib.unified_diff(e_lines, a_lines, "期待結果", "出力", n=0))
    shown = diff[:MAX_DIFF_LINES]
    text = "".join(line if line.endswith("\n") else line + "\n" for line in shown)
    if len(diff) > MAX_DIFF_LINES:
        text += "... (差分は他に %d 行あります)\n" % (len(diff) - MAX_DIFF_LINES)
    return text


def compare_with_expected(paths, expected_dir, out):
    """書き出した各ファイルと、期待結果ディレクトリ直下の同名ファイルを内容(バイト列)で比較する。"""
    if not os.path.isdir(expected_dir):
        raise ToolError("期待結果ディレクトリが存在しないか、ディレクトリではありません: %s" % expected_dir)
    problems = []
    for path in paths:
        name = os.path.basename(path)
        exp_path = os.path.join(expected_dir, name)
        if not os.path.isfile(exp_path):
            problems.append("%s: 期待結果ファイルがありません (%s)\n" % (name, exp_path))
            continue
        try:
            with open(path, "rb") as f:
                actual = f.read()
            with open(exp_path, "rb") as f:
                expected = f.read()
        except OSError as exc:
            raise ToolError("比較のためにファイルを読めません: %s (%s)" % (name, exc))
        if actual != expected:
            problems.append("%s: 期待結果と一致しません\n%s" % (name, _describe_diff(actual, expected)))
    if problems:
        raise ToolError("期待結果との比較に失敗しました\n" + "".join(problems).rstrip("\n"))
    out.write("期待結果と完全に一致しました (%d ファイル)\n" % len(paths))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="noim_converter.py",
        description="3つの入力CSV(ノード/エンティティ/サービス)をNOIM形式に変換して出力ディレクトリへ書き出す")
    parser.add_argument("input_dir", help="入力ディレクトリ")
    parser.add_argument("output_dir", help="出力ディレクトリ(なければ作成)")
    parser.add_argument("--expected", metavar="DIR", default=None,
                        help="期待結果ディレクトリ(指定時のみ、書き出した8ファイルと内容を比較)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # 引数エラーは 2
        return exc.code if isinstance(exc.code, int) else 2
    try:
        run(args.input_dir, args.output_dir, args.expected)
    except ToolError as exc:
        sys.stderr.write("エラー: %s\n" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
