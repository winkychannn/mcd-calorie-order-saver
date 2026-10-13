#!/usr/bin/env python3
"""从真实 MCP 数据生成 README 配图（纯标准库，无第三方依赖）。

产出：
  docs/plan-scatter.svg  热量 × 价格 散点图（目标区间高亮 + 推荐点标注）
  docs/flow.svg          六步工作流示意图

数据来源：tests/gz-1400205-output.json（广州华夏路餐厅真实菜单，2026-10-13 实测）
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs")
os.makedirs(OUT, exist_ok=True)

FONT = "PingFang SC, Hiragino Sans GB, Microsoft YaHei, Helvetica, Arial, sans-serif"
RED = "#DA291C"
YELLOW = "#FFC72C"
DARK = "#1F2328"
GREY = "#8C959F"
LIGHT = "#E8EAED"
BLUE = "#0969DA"
GREEN = "#1A7F37"


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ---------------------------------------------------------------- 散点图
def scatter():
    d = json.load(open(os.path.join(ROOT, "tests", "gz-1400205-output.json")))
    s = d["summary"]
    target = s["target_kcal"]
    budget = s["budget_yuan"]
    lo, hi = s["kcal_range"]

    W, H = 900, 520
    L, R, T, B = 74, 214, 64, 58           # 左右上下留白
    PW, PH = W - L - R, H - T - B
    XMAX, YMAX = 880.0, 36.0

    def sx(k):
        return L + k / XMAX * PW

    def sy(p):
        return T + PH - p / YMAX * PH

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
        'font-family="%s">' % (W, H, W, H, FONT),
        '<rect width="%d" height="%d" rx="10" fill="#FFFFFF" stroke="%s"/>' % (W, H, LIGHT),
        '<text x="%d" y="30" font-size="17" font-weight="700" fill="%s">'
        '热量 × 价格 —— 真实菜单里的可选空间</text>' % (L, DARK),
        '<text x="%d" y="50" font-size="12" fill="%s">'
        '麦当劳广州华夏路餐厅（storeCode 1400205）· 63 项菜单 / 5 个套餐 · 共评估 1984 个方案</text>'
        % (L, GREY),
    ]

    # 目标区间（热量 400~600 kcal 且 不超预算）
    parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" fill-opacity="0.13" '
                 'stroke="%s" stroke-opacity="0.35" stroke-dasharray="4 3"/>'
                 % (sx(lo), sy(budget), sx(hi) - sx(lo), sy(0) - sy(budget), RED, RED))
    parts.append('<text x="%.1f" y="%.1f" font-size="11" fill="%s" font-weight="600" '
                 'text-anchor="end">目标区间 %d~%d kcal</text>'
                 % (sx(lo) - 6, sy(0) - 8, RED, lo, hi))

    # 网格与刻度
    for k in range(0, 901, 100):
        parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s"/>'
                     % (sx(k), T, sx(k), T + PH, LIGHT))
        parts.append('<text x="%.1f" y="%.1f" font-size="11" fill="%s" text-anchor="middle">%d</text>'
                     % (sx(k), T + PH + 18, GREY, k))
    for p in range(0, 36, 5):
        parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s"/>'
                     % (L, sy(p), L + PW, sy(p), LIGHT))
        parts.append('<text x="%.1f" y="%.1f" font-size="11" fill="%s" text-anchor="end">%d</text>'
                     % (L - 10, sy(p) + 4, GREY, p))

    # 坐标轴
    parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.2"/>'
                 % (L, T + PH, L + PW, T + PH, DARK))
    parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.2"/>'
                 % (L, T, L, T + PH, DARK))
    parts.append('<text x="%.1f" y="%.1f" font-size="12" fill="%s" text-anchor="middle">'
                 '热量（kcal）</text>' % (L + PW / 2, H - 16, DARK))
    parts.append('<text x="16" y="%.1f" font-size="12" fill="%s" text-anchor="middle" '
                 'transform="rotate(-90 16 %.1f)">实付价格（元）</text>' % (T + PH / 2, DARK, T + PH / 2))

    # 预算线
    parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.6" '
                 'stroke-dasharray="7 4"/>' % (L, sy(budget), L + PW, sy(budget), RED))
    parts.append('<text x="%.1f" y="%.1f" font-size="11.5" fill="%s" font-weight="600">'
                 '预算上限 %g 元</text>' % (L + 8, sy(budget) - 7, RED, budget))
    # 目标热量线
    parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.4" '
                 'stroke-dasharray="7 4"/>' % (sx(target), T, sx(target), T + PH, BLUE))
    parts.append('<text x="%.1f" y="%.1f" font-size="11.5" fill="%s" font-weight="600" '
                 'text-anchor="end">目标 %g kcal</text>' % (sx(target) - 6, T + 14, BLUE, target))

    # 全部在售单品（灰点）
    for m in d["matched"]:
        parts.append('<circle cx="%.1f" cy="%.1f" r="3.4" fill="%s" fill-opacity="0.5"/>'
                     % (sx(m["kcal"]), sy(m["price"]), GREY))

    # 备选方案（空心圆）
    for p in d["plans"]:
        if p["tag"] != "备选":
            continue
        parts.append('<circle cx="%.1f" cy="%.1f" r="5.2" fill="#FFFFFF" stroke="%s" '
                     'stroke-width="1.6"/>' % (sx(p["kcal"]), sy(p["price"]), GREY))

    # 四个推荐点
    HL = {
        "最贴热量": (RED, "#FFFFFF"),
        "最省钱": ("#E8862A", "#FFFFFF"),
        "最平衡": (BLUE, "#FFFFFF"),
        "套餐优选": (GREEN, "#FFFFFF"),
    }
    # 标签位置微调，避免重叠
    OFFSET = {
        "最贴热量": (8, 20, "start"),
        "最省钱": (9, -8, "start"),
        "最平衡": (-9, 4, "end"),
        "套餐优选": (9, 4, "start"),
    }
    for p in d["plans"]:
        if p["tag"] not in HL:
            continue
        col, _ = HL[p["tag"]]
        cx, cy = sx(p["kcal"]), sy(p["price"])
        parts.append('<circle cx="%.1f" cy="%.1f" r="7.6" fill="%s" stroke="#FFFFFF" '
                     'stroke-width="2"/>' % (cx, cy, col))
        dx, dy, anchor = OFFSET[p["tag"]]
        parts.append('<text x="%.1f" y="%.1f" font-size="11.5" font-weight="600" fill="%s" '
                     'text-anchor="%s">%s %g元</text>'
                     % (cx + dx, cy + dy, col, anchor, esc(p["name"]), p["price"]))

    # 图例
    lx, ly = L + PW + 22, T + 12
    parts.append('<text x="%d" y="%d" font-size="12.5" font-weight="700" fill="%s">图例</text>'
                 % (lx, ly, DARK))
    items = [
        ("dot", GREY, "在售单品（%d 项）" % len(d["matched"])),
        ("ring", GREY, "备选方案"),
        ("fill", RED, "最贴热量"),
        ("fill", "#E8862A", "最省钱"),
        ("fill", BLUE, "最平衡"),
        ("fill", GREEN, "套餐优选"),
    ]
    y = ly + 24
    for kind, col, label in items:
        if kind == "dot":
            parts.append('<circle cx="%d" cy="%d" r="3.4" fill="%s" fill-opacity="0.6"/>'
                         % (lx + 5, y - 4, col))
        elif kind == "ring":
            parts.append('<circle cx="%d" cy="%d" r="5" fill="#FFFFFF" stroke="%s" stroke-width="1.6"/>'
                         % (lx + 5, y - 4, col))
        else:
            parts.append('<circle cx="%d" cy="%d" r="6.4" fill="%s"/>' % (lx + 5, y - 4, col))
        parts.append('<text x="%d" y="%d" font-size="11.5" fill="%s">%s</text>'
                     % (lx + 18, y, DARK, esc(label)))
        y += 25

    parts.append('<text x="%d" y="%.1f" font-size="11" fill="%s">'
                 '要点：右下角越靠右下＝越省越饱</text>' % (lx, y + 12, GREY))
    parts.append('<text x="%d" y="%.1f" font-size="11" fill="%s">'
                 '两个「随心配」落在区间内、¥13.9 起</text>' % (lx, y + 30, GREY))
    parts.append('<text x="%d" y="%.1f" font-size="11" fill="%s">'
                 '同热量单点组合普遍 ¥22~27</text>' % (lx, y + 48, GREY))

    parts.append("</svg>")
    open(os.path.join(OUT, "plan-scatter.svg"), "w", encoding="utf-8").write("\n".join(parts))


# ---------------------------------------------------------------- 流程图
def flow():
    W = 900
    PAD = 26
    ROW_H = 96
    GAP = 14
    steps = [
        ("1", "采集目标", "对话",
         ["热量目标", "预算上限", "位置 / 取餐方式"],
         "一次只问 1~2 个；用户说「随便」就给默认档并说明", GREY),
        ("2", "热量匹配（含套餐拆解）", "MCP",
         ["list-nutrition-foods", "query-meals", "query-meal-detail"],
         "套餐按 rounds[] 拆组件求和；查不到营养数据的组件如实标注，不猜", RED),
        ("3", "价格与优惠券核算", "MCP",
         ["available-coupons", "query-my-coupons", "query-store-coupons"],
         "券按当次门店复核，实付＝原价−券；每次推荐必带 热量 / 原价 / 券后实付", YELLOW),
        ("4", "确认门店与取餐方式", "MCP",
         ["query-nearby-stores", "calculate-price"],
         "takeWayCode 一律取当次返回，各店取值不同，绝不硬编码", YELLOW),
        ("5", "复价确认", "MCP",
         ["calculate-price"],
         "用官方算价接口复核终价；套餐替换过组件时必须复价", BLUE),
        ("6", "创建订单 → 支付", "MCP",
         ["create-order", "query-order"],
         "未经用户明确确认绝不调用；先问选哪一档，再建单", GREEN),
    ]
    H = PAD * 2 + len(steps) * ROW_H + (len(steps) - 1) * GAP + 52
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
        'font-family="%s">' % (W, H, W, H, FONT),
        '<rect width="%d" height="%d" rx="10" fill="#FFFFFF" stroke="%s"/>' % (W, H, LIGHT),
        '<text x="%d" y="34" font-size="17" font-weight="700" fill="%s">'
        '六步工作流 —— 每一步都对应真实的 MCP 调用</text>' % (PAD, DARK),
    ]
    y = 54
    for num, title, tag, tools, note, col in steps:
        parts.append('<rect x="%d" y="%d" width="%d" height="%d" rx="9" fill="#FAFBFC" '
                     'stroke="%s"/>' % (PAD, y, W - PAD * 2, ROW_H, LIGHT))
        parts.append('<rect x="%d" y="%d" width="5" height="%d" rx="2.5" fill="%s"/>'
                     % (PAD, y, ROW_H, col))
        # 序号圆
        parts.append('<circle cx="%d" cy="%d" r="15" fill="%s"/>' % (PAD + 34, y + ROW_H / 2, col))
        parts.append('<text x="%d" y="%d" font-size="15" font-weight="700" fill="#FFFFFF" '
                     'text-anchor="middle">%s</text>' % (PAD + 34, y + ROW_H / 2 + 5.5, num))
        # 标题
        parts.append('<text x="%d" y="%d" font-size="14.5" font-weight="700" fill="%s">%s</text>'
                     % (PAD + 60, y + 30, DARK, esc(title)))
        # 工具 chips
        cx = PAD + 60
        for t in tools:
            w = 7.2 * len(t) + 18
            parts.append('<rect x="%.1f" y="%d" width="%.1f" height="21" rx="10.5" fill="#FFFFFF" '
                         'stroke="%s"/>' % (cx, y + 40, w, LIGHT))
            parts.append('<text x="%.1f" y="%d" font-size="11.5" fill="%s" '
                         'font-family="SFMono-Regular, Consolas, monospace">%s</text>'
                         % (cx + 9, y + 55, DARK, esc(t)))
            cx += w + 7
        # 关键点
        parts.append('<text x="%d" y="%d" font-size="11.5" fill="%s">%s</text>'
                     % (PAD + 60, y + 81, GREY, esc(note)))
        y += ROW_H + GAP

    parts.append('<text x="%d" y="%d" font-size="11.5" fill="%s">'
                 '⚠️ 第 6 步是真实扣款动作：确认前只给方案，确认后才建单；订单创建后由用户自行完成支付。</text>'
                 % (PAD, y + 22, RED))
    parts.append("</svg>")
    open(os.path.join(OUT, "flow.svg"), "w", encoding="utf-8").write("\n".join(parts))


scatter()
flow()
print("已生成：")
for f in sorted(os.listdir(OUT)):
    p = os.path.join(OUT, f)
    print("  docs/%-22s %6.1f KB" % (f, os.path.getsize(p) / 1024))
