#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦麦卡路里省钱下单助手 · 组合优化引擎

职责：
  1) 把 MCP 的【营养表】与【门店菜单】做名称归一化匹配；
  2) 把【套餐】拆成组件、按组件热量求和，让套餐作为一个"完整候选"参与比较
     （套餐通常比单点便宜，是很多用户的天然偏好）；
  3) 在「热量目标 ± 容差」与「预算上限」双约束下搜索，输出 Pareto 方案。

设计原则：
  - 只用标准库，无第三方依赖
  - stdin 读 JSON，stdout 写 JSON，不做任何网络请求（MCP 由 Agent 调用，数据经 stdin 传入）
  - 绝不编造营养数据：匹配不上的一律进 unmatched，并说明原因

用法：
  python3 scripts/optimize.py < input.json

输入 schema：
{
  "target_kcal": 550,                # 必填，单餐目标热量
  "kcal_tolerance": 0.20,            # 选填，默认 ±20%
  "budget_yuan": 28,                 # 必填，预算上限（元）
  "nutrition": [ {name, energyKcal, protein, fat, carbohydrate, sodium, calcium} ],
  "meals":     [ {code, name, price, category?} ],          # 单品（含套餐时会被自动跳过）
  "combos":    [                                            # 套餐，两种给法二选一
        # 给法 A：Agent 已按套餐详情选好组件（最稳，价格最准）
        {"code":"9900004064","name":"精选单人餐三件套","price":34.5,
         "single_sum":46.5,
         "components":[{"code":"1406","name":"板烧鸡腿堡","role":"main"},
                       {"code":"4810","name":"中薯条","role":"side"},
                       {"code":"3050","name":"可乐中杯","role":"drink"}]},
        # 给法 B：直接贴 query-meal-detail 的 rounds，由引擎自动挑组件
        {"code":"9900013304","name":"人气经典随心配","price":14.9,
         "rounds":[{"name":"蓝区","choices":[{"code":"1120","name":"双层吉士汉堡","isDefault":1,"diffPrice":"+ ¥0"}]},
                   {"name":"粉区","choices":[{"code":"521328","name":"可乐麦炫酷","isDefault":1,"diffPrice":"+ ¥0"},
                                             {"code":"3050","name":"可乐中杯","isDefault":0,"diffPrice":"+ ¥0"}]}]}
  ],
  "aliases":   {"薯条": "中薯条"},     # 选填，覆盖内置别名
  "max_plans": 12                    # 选填，默认 12
}

输出 schema：
{
  "summary": {...},
  "matched": [ {code,name,kcal,price,role,...} ],            # 单品候选
  "matched_combos": [ {code,name,kcal,price,components,savings,...} ],
  "unmatched": [ {code,name,reason,role} ],                  # 单品 + 套餐
  "plans": [ {rank,tag,kind,name,items,components,kcal,price,kcal_gap,kcal_pct,
              within_kcal,within_budget,price_estimated,savings_vs_single} ],
  "advice": {kcal_status,budget_status,cheapest_price,cheapest_kcal,closest_kcal,
             combo_highlights:[],suggestions:[]},
  "disclaimer": "..."
}
"""

import sys
import json
import itertools

# 内置别名表：菜单名（归一化后） -> 营养表名（归一化后）
# 仅覆盖"菜单给简称、营养表给全称"的高频歧义项；可用输入里的 aliases 覆盖。
BUILTIN_ALIASES = {
    "薯条": "中薯条",
    "可乐": "可乐中杯",
    "玉米杯": "小杯玉米杯",
    "新地": "朱古力新地",
    "派": "香芋派",
    "麦乐鸡": "麦乐鸡5块",
    "麦旋风": "奥利奥麦旋风",
    "鲜萃咖啡": "大杯鲜萃咖啡",
    "怡泉+c": "中杯怡泉+c",
    "燕麦奶": "冰燕麦奶中杯",
    "麦咖啡奶铁": "热奶铁中杯",
    "麦咖啡美式": "热美式中杯",
    "浓浓黑巧": "热浓浓黑巧中杯",
    "浓浓燕麦黑巧": "热浓浓燕麦黑巧中杯",
    "麦辣鸡翅": "麦辣鸡翅-2块",
    "阳光橙麦炫酷": "麦旋酷阳光橙",
    "香芋派": "香芋派",
    "经典麦旋风": "经典麦旋风",
}

COMBO_KW = ["套餐", "件套", "随心配", "小食盘", "双人餐", "多人餐", "任选", "四宫格", "乐园", "双拼"]
MERCH_KW = ["帽", "捶", "痒痒挠", "玩具", "公仔", "徽章", "百宝袋",
            "周边", "玩偶", "盲盒", "冰箱贴", "钥匙扣", "帆布", "杯垫"]
DRINK_KW = ["可乐", "雪碧", "咖啡", "美式", "拿铁", "奶铁", "卡布奇诺", "玛奇朵", "红茶", "茶",
            "牛奶", "豆浆", "果汁", "苹果汁", "雪冰", "燕麦奶", "纯悦", "美汁源", "怡泉",
            "阳光橙", "麦炫酷", "黑巧", "抹茶", "朱古力", "橙橙", "柠柠", "柠檬红茶"]
SIDE_KW = ["薯条", "薯饼", "派", "麦乐鸡", "鸡翅", "鸡块", "玉米杯", "冰淇淋", "新地", "麦旋风",
           "苹果片", "油条", "v翅", "鸡排", "鸡球", "芝士条", "鸡柳", "脆汁鸡", "圆筒", "小食"]

# 出现这些词但营养表没有精确/别名匹配时，禁用"子串模糊匹配"，
# 避免把"迷你草莓新地"错配到"草莓新地"而给出失真热量。
AMBIGUOUS_KW = ["迷你", "小份", "半份", "双人", "多人", "儿童"]


def norm(name):
    """名称归一化：括号统一、去空格/商标符号、转小写。"""
    if not name:
        return ""
    s = str(name)
    s = s.replace("（", "(").replace("）", ")")
    s = s.replace("™", "").replace("®", "").replace(" ", "").replace("\u3000", "")
    return s.strip().lower()


def strip_decoration(name):
    """去掉括号补充说明与常见规格后缀，用于二次匹配。"""
    s = norm(name)
    for ch in ("(", "["):
        if ch in s:
            s = s.split(ch)[0]
    for suf in ("-2块", "-带骨里脊", "-琵琶腿", "盒装"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return s.strip()


def build_nutrition_index(nutrition):
    idx = {}
    for row in nutrition or []:
        n = norm(row.get("name"))
        if n and n not in idx:
            idx[n] = row
    return idx


def resolve_nutrition(meal_name, idx, aliases):
    """把一个名称解析到营养表条目；解析不到返回 (None, 原因)。绝不猜。"""
    n = norm(meal_name)
    if not n:
        return None, "名称为空"
    if n in idx:
        return idx[n], None
    if n in aliases and aliases[n] in idx:
        return idx[aliases[n]], None

    base = strip_decoration(meal_name)
    if base and base in idx:
        return idx[base], None
    # 去括号/规格后缀后再查一次别名：
    # 菜单常见「浓浓黑巧（冰/热）」这类写法，别名表里存的是去括号后的写法。
    if base and base in aliases and aliases[base] in idx:
        return idx[aliases[base]], None

    # 含歧义词且无精确匹配时，不做子串猜测
    if any(k in n for k in AMBIGUOUS_KW):
        return None, "营养表无匹配（含规格词，不做近似匹配）"

    if base:
        cands = [k for k in idx if base in k or k in base]
        if len(cands) == 1:
            return idx[cands[0]], None
        if len(cands) > 1:
            mid = [c for c in cands if "中杯" in c]
            if len(mid) == 1:
                return idx[mid[0]], None
    return None, "营养表无匹配"


def classify(name):
    """餐品角色分类：combo / merch / sauce / drink / side / main。"""
    n = norm(name)
    if any(k in n for k in COMBO_KW):
        return "combo"
    if any(k in n for k in MERCH_KW):
        return "merch"
    if n.endswith("酱"):
        return "sauce"
    if any(k in n for k in DRINK_KW):
        return "drink"
    if any(k in n for k in SIDE_KW):
        return "side"
    return "main"


def role_from_round(round_name, choice_name):
    """根据套餐轮次名推断组件角色（主食轮 / 小食轮 / 饮料轮）。"""
    r = norm(round_name)
    if any(k in r for k in ("主食", "汉堡", "卷", "堡")):
        return "main"
    if any(k in r for k in ("小食", "配餐", "甜品", "薯")):
        return "side"
    if any(k in r for k in ("饮料", "饮品", "咖啡", "喝")):
        return "drink"
    return classify(choice_name)


def to_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_diff(diff_price):
    """把 "+ ¥2" / "- ¥0.5" 这类差价串解析成浮点元。"""
    if diff_price is None:
        return 0.0
    s = str(diff_price).replace("¥", "").replace("￥", "").replace(" ", "").replace("\u3000", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def name_similarity(a, b):
    """两个名称的相似度 = 最长公共子串长度（归一化后比较）。
       用于套餐替换时判断「谁和默认项才是同类」：
       "可乐中杯" vs 默认"可乐麦炫酷" → 2；"怡泉+C" → 0。"""
    x, y = norm(a), norm(b)
    if not x or not y:
        return 0
    prev = [0] * (len(y) + 1)
    best = 0
    for i in range(1, len(x) + 1):
        cur = [0] * (len(y) + 1)
        for j in range(1, len(y) + 1):
            if x[i - 1] == y[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def build_candidates(meals, idx, aliases):
    """单品候选：菜单里除套餐/周边/酱料外的单品。"""
    matched, unmatched = [], []
    for m in meals or []:
        code = str(m.get("code", "")).strip()
        name = m.get("name", "")
        if not code:
            continue
        role = classify(name)
        if role in ("combo", "merch", "sauce"):
            continue  # 组合/周边/酱料不参与单品优化（套餐走 build_combo_candidates）
        row, reason = resolve_nutrition(name, idx, aliases)
        price = to_float(m.get("price"))
        if row is None:
            unmatched.append({"code": code, "name": name, "reason": reason, "role": role})
            continue
        kcal = to_float(row.get("energyKcal"))
        if kcal <= 0 and role != "drink":
            unmatched.append({"code": code, "name": name, "reason": "热量为 0 或缺失", "role": role})
            continue
        matched.append({
            "code": code, "name": name, "kcal": kcal, "price": price, "role": role,
            "protein": to_float(row.get("protein")), "fat": to_float(row.get("fat")),
            "carbohydrate": to_float(row.get("carbohydrate")),
            "sodium": to_float(row.get("sodium")), "calcium": to_float(row.get("calcium")),
        })
    return matched, unmatched


def _pick_component_for_round(rnd, idx, aliases, subs):
    """在一轮选配里挑一个"有营养数据"的组件：
       优先默认项；默认项无营养数据时，退而选择替代项——
       先在「接近最低差价（+1 元以内）」的候选里挑，再优先选与默认项名称最像的，
       避免出现"默认是可乐、却被换成一瓶柠檬茶"这种观感很怪的替换。"""
    choices = rnd.get("choices") or []
    default = next((c for c in choices if c.get("isDefault") == 1), None)
    if default is not None:
        row, _ = resolve_nutrition(default.get("name", ""), idx, aliases)
        if row is not None:
            return default, row
    cands = []
    for c in choices:
        row, _ = resolve_nutrition(c.get("name", ""), idx, aliases)
        if row is not None:
            cands.append((c, row))
    if not cands:
        return None, None

    default_name = default.get("name", "") if default is not None else ""
    cheapest_diff = min(parse_diff(c[0].get("diffPrice")) for c in cands)
    near = [cr for cr in cands if parse_diff(cr[0].get("diffPrice")) <= cheapest_diff + 1.0]
    near.sort(key=lambda cr: (-name_similarity(default_name, cr[0].get("name", "")),
                              parse_diff(cr[0].get("diffPrice")),
                              str(cr[0].get("name"))))
    pick, row = near[0]

    if default is not None and default.get("name") != pick.get("name"):
        d = parse_diff(pick.get("diffPrice"))
        subs.append("%s → %s%s" % (default.get("name"), pick.get("name"),
                                   ("（差价 %+.1f 元）" % d) if abs(d) > 1e-9 else ""))
    return pick, row


def build_combo_candidates(combos, idx, aliases):
    """套餐候选：拆成组件、按组件热量求和；组件热量不全则整体判为未匹配（不猜）。"""
    matched, unmatched = [], []
    for cb in combos or []:
        code = str(cb.get("code", "")).strip()
        name = cb.get("name", "")
        if not code:
            continue
        base_price = to_float(cb.get("price"))
        subs = []
        chosen = []          # [{code,name,role,kcal,diff}]
        missing = []         # 无法解析的组件描述

        if cb.get("components"):
            for c in cb["components"]:
                row, _ = resolve_nutrition(c.get("name", ""), idx, aliases)
                if row is None:
                    missing.append(c.get("name") or c.get("code") or "?")
                    continue
                chosen.append({
                    "code": str(c.get("code", "")), "name": c.get("name", ""),
                    "role": c.get("role") or classify(c.get("name", "")),
                    "kcal": to_float(row.get("energyKcal")), "diff": 0.0,
                })
        elif cb.get("rounds"):
            for rnd in cb["rounds"]:
                pick, row = _pick_component_for_round(rnd, idx, aliases, subs)
                if pick is None:
                    missing.append(rnd.get("name") or "某个选配轮次")
                    continue
                chosen.append({
                    "code": str(pick.get("code", "")), "name": pick.get("name", ""),
                    "role": role_from_round(rnd.get("name", ""), pick.get("name", "")),
                    "kcal": to_float(row.get("energyKcal")),
                    "diff": parse_diff(pick.get("diffPrice")),
                })
        else:
            unmatched.append({"code": code, "name": name, "reason": "套餐无组件信息", "role": "combo"})
            continue

        if missing:
            unmatched.append({
                "code": code, "name": name, "role": "combo",
                "reason": "组件无营养数据：" + "、".join(str(x) for x in missing),
            })
            continue
        if not chosen:
            unmatched.append({"code": code, "name": name, "role": "combo", "reason": "套餐无可解析组件"})
            continue

        price = round(base_price + sum(c["diff"] for c in chosen), 2)
        kcal = round(sum(c["kcal"] for c in chosen), 1)
        single_sum = cb.get("single_sum")
        single_sum = to_float(single_sum) if single_sum not in (None, "", 0) else None
        savings = round(single_sum - price, 2) if single_sum else None

        matched.append({
            "code": code, "name": name, "kcal": kcal, "price": price, "role": "combo",
            "components": [{"code": c["code"], "name": c["name"], "role": c["role"], "kcal": c["kcal"]}
                           for c in chosen],
            "substituted": subs,
            "price_estimated": bool(subs),
            "single_sum": single_sum,
            "savings": savings if (savings is not None and savings > 0) else None,
        })
    return matched, unmatched


def _score(p, target_kcal, budget):
    k = abs(p["kcal_gap"]) / target_kcal if target_kcal else 0
    m = p["price"] / budget if budget else 0
    return 0.55 * k + 0.45 * m


def key_of(plan):
    return tuple(sorted(i["code"] for i in plan["items"]))


def search_plans(matched, target_kcal, tolerance, budget):
    """自选组合：1 主食 + 0~1 小食 + 0~1 饮品。"""
    mains = [c for c in matched if c["role"] == "main"]
    sides = [c for c in matched if c["role"] == "side"]
    drinks = [c for c in matched if c["role"] == "drink"]

    lo, hi = target_kcal * (1 - tolerance), target_kcal * (1 + tolerance)
    plans = []
    for main, side, drink in itertools.product(mains, [None] + sides, [None] + drinks):
        combo = [x for x in (main, side, drink) if x is not None]
        kcal = sum(x["kcal"] for x in combo)
        price = round(sum(x["price"] for x in combo), 2)
        plans.append({
            "kind": "assemble",
            "name": " + ".join(x["name"] for x in combo),
            "items": combo, "components": None, "substituted": [], "price_estimated": False,
            "kcal": round(kcal, 1), "price": price,
            "kcal_gap": round(kcal - target_kcal, 1),
            "kcal_pct": round(kcal / target_kcal * 100, 1) if target_kcal else None,
            "within_budget": price <= budget + 1e-6,
            "within_kcal": lo <= kcal <= hi,
            "savings": None,
        })
    return plans


def combos_to_plans(matched_combos, target_kcal, tolerance, budget):
    """把套餐候选转成 plan（套餐本身就是一份完整餐）。"""
    lo, hi = target_kcal * (1 - tolerance), target_kcal * (1 + tolerance)
    plans = []
    for cb in matched_combos:
        plans.append({
            "kind": "combo",
            "name": cb["name"],
            "items": [{"code": cb["code"], "name": cb["name"], "kcal": cb["kcal"],
                       "price": cb["price"], "role": "combo"}],
            "components": cb["components"],
            "substituted": cb["substituted"],
            "price_estimated": cb["price_estimated"],
            "kcal": cb["kcal"], "price": cb["price"],
            "kcal_gap": round(cb["kcal"] - target_kcal, 1),
            "kcal_pct": round(cb["kcal"] / target_kcal * 100, 1) if target_kcal else None,
            "within_budget": cb["price"] <= budget + 1e-6,
            "within_kcal": lo <= cb["kcal"] <= hi,
            "savings": cb["savings"],
            "single_sum": cb["single_sum"],
        })
    return plans


def pick_top(plans, target_kcal, budget, n):
    """挑代表方案：最贴热量 / 最省钱 / 最平衡 / 套餐优选 / 备选。"""
    if not plans:
        return []
    in_both = [p for p in plans if p["within_kcal"] and p["within_budget"]]
    in_kcal = [p for p in plans if p["within_kcal"]]
    pool = in_both or in_kcal or plans

    by_kcal = sorted(pool, key=lambda p: (abs(p["kcal_gap"]), p["price"]))
    by_price = sorted(pool, key=lambda p: (p["price"], abs(p["kcal_gap"])))
    by_score = sorted(pool, key=lambda p: _score(p, target_kcal, budget))

    strategies = [("最贴热量", by_kcal), ("最省钱", by_price), ("最平衡", by_score)]

    # 套餐优选：预算内的套餐单独占一个展示位（套餐通常比单点便宜，是很多用户的天然偏好）。
    # 只考虑预算内的：既超热量又超预算的套餐不该推给用户，交给 advice 里如实说明即可。
    combo_pool = sorted([p for p in plans if p["kind"] == "combo" and p["within_budget"]],
                        key=lambda p: (0 if p["within_kcal"] else 1,
                                       -(p.get("savings") or 0), p["price"], abs(p["kcal_gap"])))
    if combo_pool:
        strategies.append(("套餐优选", combo_pool))

    chosen, seen = [], set()
    for tag, cand in strategies:
        for p in cand:
            k = key_of(p)
            if k in seen:
                continue
            seen.add(k)
            chosen.append((tag, p))
            break

    if len(chosen) < n:
        for p in by_score + combo_pool:
            k = key_of(p)
            if k in seen:
                continue
            seen.add(k)
            chosen.append(("备选", p))
            if len(chosen) >= n:
                break

    return chosen[:n]


def make_advice(plans, combo_plans, target_kcal, budget):
    in_both = [p for p in plans if p["within_kcal"] and p["within_budget"]]
    in_kcal = [p for p in plans if p["within_kcal"]]
    pool = in_both or in_kcal or plans
    cheapest = min(pool, key=lambda p: p["price"]) if pool else None
    closest = min(pool, key=lambda p: abs(p["kcal_gap"])) if pool else None
    lightest = min(pool, key=lambda p: p["kcal"]) if pool else None
    within_budget = [p for p in plans if p["within_budget"]]

    if in_kcal and within_budget:
        kcal_status, budget_status = "ok", "ok"
    elif not in_kcal:
        kcal_status = "no_kcal_hit"
        budget_status = "ok" if within_budget else "over"
    else:
        kcal_status = "ok"
        budget_status = "over" if not within_budget else "ok"

    # 套餐省钱榜（给展示用）：优先放在热量区间内的，其次按省得多排序
    highlights = []
    ordered = sorted(combo_plans, key=lambda c: (0 if (c["within_kcal"] and c["within_budget"]) else 1,
                                                 -((c["single_sum"] - c["price"]) if c["single_sum"] else 0),
                                                 c["price"]))
    for cb in ordered[:5]:
        highlights.append({
            "name": cb["name"], "price": cb["price"], "kcal": cb["kcal"],
            "single_sum": cb.get("single_sum"),
            "savings": (round(cb["single_sum"] - cb["price"], 2) if cb.get("single_sum") else None),
            "within_kcal": cb["within_kcal"], "within_budget": cb["within_budget"],
        })

    suggestions = []
    if not plans:
        suggestions.append("候选为空：可能是菜单为空或营养表全部未匹配，请先确认 MCP 数据是否取到。")
    else:
        if kcal_status == "no_kcal_hit" and closest:
            suggestions.append(
                "热量目标附近暂时没有合适组合。最接近的是 %s kcal（与目标差 %s kcal）。"
                % (closest["kcal"], closest["kcal_gap"]))
        if budget_status == "over" and cheapest:
            suggestions.append(
                "预算内暂时没有合适组合。最省的一档是 %s 元，比预算高 %s 元。"
                % (cheapest["price"], round(cheapest["price"] - budget, 2)))
        if kcal_status == "no_kcal_hit" and closest and closest["kcal"] > target_kcal:
            suggestions.append("方向一：把热量目标放宽到 %s kcal 左右，可选空间会明显变大。" % int(closest["kcal"]))
        if kcal_status == "no_kcal_hit" and lightest and lightest["kcal"] > target_kcal:
            suggestions.append("方向二：当前菜单能凑出的最低热量是 %s kcal，已经高于目标，可以拆成「小食 + 饮品」的轻组合，或把目标上调一点。" % int(lightest["kcal"]))
        if kcal_status == "no_kcal_hit":
            suggestions.append("方向三：把高热量主食换成低卡单品（如麦香鱼、板烧鸡腿堡、麦香鸡）再试一次。")
        if budget_status == "over":
            suggestions.append("方向四：保持热量不变，用更省的同款替代（可乐改小食、薯条改小份）压一压预算。")
        if highlights:
            best_save = max([h["savings"] or 0 for h in highlights] or [0])
            if best_save > 0:
                suggestions.append("顺带一提：这份菜单里有 %d 个套餐可以拆开算，单点加起来比套餐最多贵 %s 元，值得先看看「套餐优选」那一档。"
                                   % (len(highlights), best_save))
            else:
                suggestions.append("顺带一提：这份菜单里有 %d 个套餐可以拆开算，热门套餐通常比单点更划算，可以看看「套餐优选」那一档。" % len(highlights))
    return {
        "kcal_status": kcal_status,
        "budget_status": budget_status,
        "cheapest_price": cheapest["price"] if cheapest else None,
        "cheapest_kcal": cheapest["kcal"] if cheapest else None,
        "closest_kcal": closest["kcal"] if closest else None,
        "closest_kcal_gap": closest["kcal_gap"] if closest else None,
        "combo_highlights": highlights,
        "suggestions": suggestions,
    }


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        print(json.dumps({"error": "stdin 为空"}, ensure_ascii=False))
        return 1
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": "JSON 解析失败: %s" % e}, ensure_ascii=False))
        return 1

    target_kcal = to_float(payload.get("target_kcal"))
    budget = to_float(payload.get("budget_yuan"))
    tolerance = to_float(payload.get("kcal_tolerance"), 0.20)
    max_plans = int(payload.get("max_plans", 12) or 12)
    if target_kcal <= 0:
        print(json.dumps({"error": "target_kcal 必须为正数"}, ensure_ascii=False))
        return 1

    idx = build_nutrition_index(payload.get("nutrition"))
    aliases = dict(BUILTIN_ALIASES)
    for k, v in (payload.get("aliases") or {}).items():
        aliases[norm(k)] = norm(v)

    matched, unmatched_items = build_candidates(payload.get("meals"), idx, aliases)
    matched_combos, unmatched_combos = build_combo_candidates(payload.get("combos"), idx, aliases)

    assembled = search_plans(matched, target_kcal, tolerance, budget)
    combo_plans = combos_to_plans(matched_combos, target_kcal, tolerance, budget)
    all_plans = assembled + combo_plans

    top = pick_top(all_plans, target_kcal, budget, max_plans)

    out_plans = []
    for i, (tag, p) in enumerate(top, 1):
        out_plans.append({
            "rank": i, "tag": tag, "kind": p["kind"], "name": p["name"],
            "items": [{"code": x["code"], "name": x["name"], "kcal": x["kcal"],
                       "price": x["price"], "role": x["role"], "quantity": 1} for x in p["items"]],
            "components": p["components"],
            "substituted": p["substituted"],
            "price_estimated": p["price_estimated"],
            "kcal": p["kcal"], "price": p["price"],
            "kcal_gap": p["kcal_gap"], "kcal_pct": p["kcal_pct"],
            "within_kcal": p["within_kcal"], "within_budget": p["within_budget"],
            "savings_vs_single": p["savings"],
        })

    result = {
        "summary": {
            "target_kcal": target_kcal,
            "kcal_tolerance": tolerance,
            "kcal_range": [round(target_kcal * (1 - tolerance), 1), round(target_kcal * (1 + tolerance), 1)],
            "budget_yuan": budget,
            "nutrition_entries": len(idx),
            "menu_entries": len(payload.get("meals") or []),
            "combo_entries": len(payload.get("combos") or []),
            "matched": len(matched),
            "matched_combos": len(matched_combos),
            "unmatched": len(unmatched_items) + len(unmatched_combos),
            "assembled_plans": len(assembled),
            "combo_plans": len(combo_plans),
            "total_plans_evaluated": len(all_plans),
        },
        "matched": sorted(matched, key=lambda x: (x["role"], x["price"])),
        "matched_combos": sorted(matched_combos, key=lambda x: x["price"]),
        "unmatched": unmatched_items + unmatched_combos,
        "plans": out_plans,
        "advice": make_advice(all_plans, combo_plans, target_kcal, budget),
        "disclaimer": "本结果基于麦当劳 MCP 实时数据计算，仅供搭配参考，不构成医疗或营养专业建议。价格与供应以麦当劳官方渠道为准。",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
