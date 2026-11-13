"""力指向レイアウト(標準ライブラリのみ、決定的)。同じ入力からは同じ座標になる(FR6.2)。

- 線につながる装置は力指向で配置する。点同士の距離は広めにし、最後にラベルが重ならないよう押し広げる。
- 線につながらない装置(接続なし)は、図の左端に格子状にまとめて置く。
"""

import math

WIDTH = 2400.0   # 座標の上限(実際の配置領域は装置数から決める)
HEIGHT = 1600.0
MARGIN = 60.0
ITERATIONS = 300

LABEL_FONT = 9.0          # ラベルの文字の大きさ(SVG単位)
LABEL_MAX_CHARS = 12      # ラベルに出す最大文字数(超えたら「…」)
LABEL_PAD = 8.0           # ラベル幅の余白
NODE_BOX_H = 40.0         # 点+ラベルの縦の大きさの目安(これ以上縦に離れていれば重ならない)
LABEL_GAP = 14.0          # ラベル同士の最小の隙間
ISO_COL_W = 160.0         # 「接続なし」格子の列の間隔
ISO_ROW_H = 64.0          # 同、行の間隔
ISO_MAX_ROWS = 6
CELL_W = 230.0            # 線につながる装置1つあたりの領域の目安
CELL_H = 150.0


def short_label(name):
    return name if len(name) <= LABEL_MAX_CHARS else name[:LABEL_MAX_CHARS] + u"…"


def label_width(label):
    """ラベルの幅の目安(全角は文字サイズ、半角は約0.58倍)。"""
    return sum(LABEL_FONT * (0.58 if ord(ch) < 128 else 1.0) for ch in label) + LABEL_PAD


def layout_graph(graph):
    """build_graph の結果から {id: (x, y)} を作る(ラベルの幅を考慮する)。"""
    ids = [d["id"] for d in graph["devices"]]
    labels = dict((d["id"], short_label(d["name"])) for d in graph["devices"])
    return compute_layout(ids, graph["edges"], labels)


def _force_layout(ids, pairs_ids, x0, y0, w, h):
    """力指向。ids は装置id列、pairs_ids は (id, id) の辺。領域 (x0, y0, w, h) に収めて {id: [x, y]} を返す。"""
    n = len(ids)
    if n == 1:
        return {ids[0]: [x0 + w / 2, y0 + h / 2]}
    index = dict((d, i) for i, d in enumerate(ids))
    cx, cy = w / 2, h / 2
    pos = []
    for i in range(n):
        ang = 2 * math.pi * i / n
        rad = (0.30 + 0.06 * (i % 3)) * min(w, h)
        pos.append([cx + rad * math.cos(ang), cy + rad * math.sin(ang)])
    pairs = sorted(set((min(index[a], index[b]), max(index[a], index[b])) for a, b in pairs_ids))

    k = math.sqrt(w * h / n) * 0.9
    temp = w / 8
    for _ in range(ITERATIONS):
        disp = [[0.0, 0.0] for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                dx = pos[i][0] - pos[j][0]
                dy = pos[i][1] - pos[j][1]
                dist = math.hypot(dx, dy) or 0.01
                force = k * k / dist
                fx, fy = dx / dist * force, dy / dist * force
                disp[i][0] += fx
                disp[i][1] += fy
                disp[j][0] -= fx
                disp[j][1] -= fy
        for i, j in pairs:
            dx = pos[i][0] - pos[j][0]
            dy = pos[i][1] - pos[j][1]
            dist = math.hypot(dx, dy) or 0.01
            force = dist * dist / k
            fx, fy = dx / dist * force, dy / dist * force
            disp[i][0] -= fx
            disp[i][1] -= fy
            disp[j][0] += fx
            disp[j][1] += fy
        for i in range(n):
            disp[i][0] += (cx - pos[i][0]) * 0.03
            disp[i][1] += (cy - pos[i][1]) * 0.03
            d = math.hypot(disp[i][0], disp[i][1]) or 0.01
            step = min(d, temp)
            pos[i][0] += disp[i][0] / d * step
            pos[i][1] += disp[i][1] / d * step
        temp = max(temp * 0.985, 0.5)

    xs = [p[0] for p in pos]
    ys = [p[1] for p in pos]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    span_x = (max_x - min_x) or 1.0
    span_y = (max_y - min_y) or 1.0
    return dict((d, [x0 + (pos[i][0] - min_x) / span_x * w, y0 + (pos[i][1] - min_y) / span_y * h])
                for d, i in index.items())


def _separate(pos, ids, widths, fixed):
    """ラベルが重ならないよう、重なる組を軸方向に押し広げる(決定的)。fixed の装置は動かさない。"""
    for _ in range(400):
        moved = False
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                i, j = ids[a], ids[b]
                need_x = (widths[i] + widths[j]) / 2 + LABEL_GAP
                dx = pos[j][0] - pos[i][0]
                dy = pos[j][1] - pos[i][1]
                if abs(dx) >= need_x or abs(dy) >= NODE_BOX_H:
                    continue
                moved = True
                if dx == 0 and dy == 0:
                    dx = 0.01 * (1 if a % 2 == 0 else -1)
                # 重なりの浅い軸のほうへ押す
                if need_x - abs(dx) <= NODE_BOX_H - abs(dy):
                    push, axis, sign = need_x - abs(dx) + 1, 0, (1 if dx >= 0 else -1)
                else:
                    push, axis, sign = NODE_BOX_H - abs(dy) + 1, 1, (1 if dy >= 0 else -1)
                fi, fj = i in fixed, j in fixed
                if fi and fj:
                    continue
                share_i = 0.0 if fi else (1.0 if fj else 0.5)
                share_j = 0.0 if fj else (1.0 if fi else 0.5)
                pos[i][axis] -= sign * push * share_i
                pos[j][axis] += sign * push * share_j
        if not moved:
            break


def compute_layout(device_ids, edges, labels=None):
    """装置のid列と辺から、{id: (x, y)} を返す。辺は source/target を持つ辞書。
    labels={id: ラベル文字列} を渡すと、そのラベルの幅で重ならないようにする。"""
    if not device_ids:
        return {}
    labels = labels or {}
    widths = dict((d, label_width(labels.get(d, u"")) if d in labels else 100.0) for d in device_ids)

    ids = list(device_ids)
    in_edge = set()
    pairs_ids = []
    known = set(ids)
    for e in edges:
        if e["source"] in known and e["target"] in known and e["source"] != e["target"]:
            in_edge.add(e["source"])
            in_edge.add(e["target"])
            pairs_ids.append((e["source"], e["target"]))
    connected = [d for d in ids if d in in_edge]
    isolated = [d for d in ids if d not in in_edge]

    pos = {}
    # 接続なし: 左端に格子状
    cols = 0
    if isolated:
        rows = min(ISO_MAX_ROWS, len(isolated))
        cols = int(math.ceil(len(isolated) / float(rows)))
        for n, d in enumerate(isolated):
            c, r = n // rows, n % rows
            pos[d] = [MARGIN + ISO_COL_W / 2 + c * ISO_COL_W, MARGIN + 40 + r * ISO_ROW_H]
    main_x0 = MARGIN + (cols * ISO_COL_W + 80 if cols else 0)

    # 線につながる装置: 力指向
    if connected:
        area = len(connected) * CELL_W * CELL_H
        w = max(math.sqrt(area * 1.6), 360.0)
        h = max(area / w, 240.0)
        pos.update(_force_layout(connected, pairs_ids, main_x0 + 90, MARGIN + 40, w, h))

    _separate(pos, ids, widths, set(isolated))

    result = {}
    for d in ids:
        x = min(max(pos[d][0], 0.0), WIDTH)
        y = min(max(pos[d][1], 0.0), HEIGHT)
        result[d] = (round(x, 1), round(y, 1))
    return result
