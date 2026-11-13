#!/usr/bin/env python3
"""NOIM構成図の可視化(PoC)。

NOIM変換ツールの出力CSVとアラームJSONを読み、構成図(装置=点、接続=線)とアラーム装置の強調を含む
自己完結のHTMLを1つ書き出す。

使い方:
    python3 visualizer.py <NOIM出力ディレクトリ> <アラームJSON> <出力HTML>

終了ステータス: 0 成功 / 1 入力・処理の失敗(HTMLは作らない) / 2 引数エラー
"""

import argparse
import os
import sys

from noim_viz.errors import VizError
from noim_viz.graph import build_graph
from noim_viz.html_out import render_html
from noim_viz.layout import layout_graph
from noim_viz.loader import load_alarms, load_noim


def run(noim_dir, alarm_path, html_path, out=None):
    """読み込み -> 組み立て -> 配置 -> HTML生成 -> 書き出し。失敗は VizError(その場合HTMLは作らない)。"""
    out = out or sys.stdout
    noim = load_noim(noim_dir)
    alarms = load_alarms(alarm_path)
    graph = build_graph(noim, alarms)
    positions = layout_graph(graph)
    html = render_html(graph, positions)

    if os.path.isdir(html_path):
        raise VizError("出力先がディレクトリです: %s" % html_path)
    tmp = html_path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(html)
        os.replace(tmp, html_path)
    except OSError as exc:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise VizError("HTMLを書き込めません: %s (%s)" % (html_path, exc))

    s = graph["summary"]
    out.write("HTMLを書き出しました: %s\n" % html_path)
    out.write("装置 %d / 物理接続 %d / LSP接続 %d / 接続なし %d / アラーム装置 %d / 対応する装置のないアラーム %d / 警告 %d\n" % (
        s["devices"], s["physical_edges"], s["lsp_edges"], s["isolated_devices"], s["alarm_devices"],
        s["unmatched_alarms"], s["warnings"]))
    for w in graph["warnings"]:
        out.write("警告: %s\n" % w)
    return graph


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="visualizer.py",
        description="NOIM変換ツールの出力CSVとアラームJSONから、構成図のHTMLを作る")
    parser.add_argument("noim_dir", help="NOIM出力ディレクトリ(resourceInfo_*.csv があるところ)")
    parser.add_argument("alarm_json", help="アラームJSON")
    parser.add_argument("output_html", help="出力するHTMLファイル")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # 引数エラーは 2
        return exc.code if isinstance(exc.code, int) else 2
    try:
        run(args.noim_dir, args.alarm_json, args.output_html)
    except VizError as exc:
        sys.stderr.write("エラー: %s\n" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
