# MCP 集成说明

本文件说明「麦麦卡路里省钱下单助手」实际使用的麦当劳 MCP Server、Tool、调用流程与业务价值。

## 一、使用的 MCP Server

| 项 | 值 |
|---|---|
| Server 名称 | `mcd-mcp` |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | streamablehttp |
| 鉴权方式 | HTTP Header：`Authorization: Bearer <MCD_MCP_TOKEN>` |
| Token 获取 | [open.mcd.cn](https://open.mcd.cn) 登录后于「控制台」激活申请 |

配置示例见 `mcp-config.example.json`（仅使用环境变量占位符，不含真实凭证）。

## 二、使用的 Tool 清单

### 核心链路（必需）

| Tool | 在项目中的用途 |
|---|---|
| `query-nearby-stores` | 按「城市 + 关键词」定位到店自取门店，拿到 `storeCode` |
| `query-meals` | 拉取该门店在售菜单，得到每个餐品的 `code`、`name`、`currentPrice`（元）、`originalPrice`（划线价） |
| `query-meal-detail` | **拆解套餐**：拿到 `rounds[]` 选配轮次与每轮默认组件（`isDefault=1`），用于按组件热量求和 |
| `list-nutrition-foods` | 拉取餐品营养数据（`energyKcal` / 蛋白质 / 脂肪 / 碳水 / 钠 / 钙），作为热量约束与套餐组件热量求和的计算依据 |
| `calculate-price` | 含券复价，得到原价、优惠金额与实付；同时拿到 `takeWayList` 供下单使用。**实测套餐可直接算价** |

### 优惠券

| Tool | 在项目中的用途 |
|---|---|
| `available-coupons` | 查询当前可领取的麦麦省券 |
| `auto-bind-coupons` | 经用户同意后一键领取可用券 |
| `query-my-coupons` | 查询用户卡包中已有券 |
| `query-store-coupons` | 复核「指定门店 + 渠道」真正可用的券（含适用商品 `productCode`），下单前必须用它 |

### 地址与下单

| Tool | 在项目中的用途 |
|---|---|
| `delivery-query-addresses` | 麦乐送场景查询用户已有地址 |
| `delivery-create-address` | 地址为空时创建配送地址 |
| `delivery-query-stores` | 按地址查可配送门店，拿 `beCode` |
| `create-order` | 用户确认后创建订单（到店场景需 `takeWayCode`；**点套餐需传 `roundList` 子项**） |
| `query-order` | 支付后查询订单状态 |
| `cancel-order` | 取消订单 |

### 辅助

| Tool | 用途 |
|---|---|
| `now-time-info` | 获取服务器时间，用于判断券是否在有效期内、门店是否在营业时段 |
| `campaign-calendar` | 查询当月营销活动 |

> **未使用的 Tool**：积分链路的 `query-my-account` / `mall-points-products` / `mall-product-detail` / `mall-create-order`，以及团餐相关的 `party-*`。原因见「四、设计取舍」。

## 三、调用流程

```
【第 1 步 · 热量匹配（含套餐拆解）】
  query-nearby-stores(city, keyword, beType=1)
      └→ storeCode
  query-meals(storeCode, orderType=1, beType=1)
      └→ 菜单：[{code, name, currentPrice, originalPrice}]
  list-nutrition-foods()
      └→ 营养表：[{name, energyKcal, protein, fat, carbohydrate, sodium, calcium}]
  ↓ 对名字含「套餐/件套/随心配/小食盘」的餐品逐个拆解
  query-meal-detail(storeCode, orderType=1, beType=1, code)
      └→ rounds[].choices[]（isDefault=1 为默认组件、diffPrice 为差价）
      └→ 组装成 combos:[{code, name, price, single_sum, rounds|components}]
  ↓ 三份数据 + 用户约束送入本地引擎
  scripts/optimize.py
      └→ matched / matched_combos / unmatched / plans(Pareto 含套餐优选) / advice

【第 2 步 · 券匹配】
  available-coupons()  /  query-my-coupons()  /  query-store-coupons(storeCode, orderType, beType)

【第 3 步 · 地址与取餐方式】
  到店自取 → 直接确认门店（storeCode）
  麦乐送   → delivery-query-addresses →（为空则 delivery-create-address）→ delivery-query-stores(beCode)

【第 4 步 · 复价确认】
  calculate-price(storeCode, orderType, beType, items[productCode+quantity+couponId])
      └→ 原价 / 优惠 / 实付 / takeWayList

【第 5 步 · 下单】
  create-order(storeCode, orderType, beType, takeWayCode, items[, roundList])
      └→ 订单号 + 支付链接（实测约 15 分钟内有效）
  query-order(orderId)  → 支付后复述最新状态
```

## 四、业务价值

1. **把"四件麻烦事"压成一句话**：热量核算、价格比较、找可用券、判断套餐划不划算，原本要在菜单、计算器、卡包之间来回切，现在一次完成。
2. **套餐拆解是本项目的核心差异点**。营养表里没有组合餐，多数同类工具因此直接跳过套餐；本项目用 `query-meal-detail` 把套餐拆成组件、按组件热量求和，让套餐作为一个完整候选参与双约束比价。实测中，**最划算的两档答案往往都是套餐**（550 kcal 档位下，套餐仅 13.9~14.9 元，明显低于同热量单点组合）。
3. **套餐默认组件缺营养数据时也不放弃**：在同一选配轮次里改选"有营养数据、与默认项名称最像、差价接近最低"的组件，并显式标记替换记录与 `price_estimated`，提醒复价。既不猜数据，也不白白丢掉一个便宜的选项。
4. **券按门店校验，不空谈优惠**：`query-my-coupons` 只说"你有这张券"，`query-store-coupons` 才说"这家店能用"。项目坚持用后者复核，避免给出用不了的券。
5. **不编数据的可信度**：营养表覆盖不到的餐品与新品，如实标注"营养表无匹配"并在输出里列出原因，而不是用大模型猜热量。
6. **从"推荐"走到"下单"**：不止停在建议，而是串到门店确认、复价、创建订单、支付引导，形成闭环。**该链路已用真实门店实测跑通**——广州华夏路店「精选超值随心配」13.9 元订单创建成功并返回支付链接。

## 五、设计取舍：为什么不做积分抵扣

- `calculate-price` **没有"积分抵扣"参数**，积分无法直接抵现。
- 能抵现的唯一路径是「积分商城兑换餐品券（`mall-points-products` → `mall-product-detail` → `mall-create-order`）→ 券再回填进算价」。这条链路需要额外 4 次工具调用，且返回里混有已过期商品，需逐条核对上下架时间。
- 它与"卡路里 + 省钱"的核心叙事关联度低，却显著拉长主流程。因此本项目**显式排除积分场景**，聚焦「券 + 套餐拆解」这条确定性更高的链路。用户主动问起时一句话说明，不做虚假承诺。

## 六、关键实现约束

- **价格单位**：`calculate-price` 返回的价格单位为「分」，展示前统一 `/100` 转元；`query-meals` 的 `currentPrice` 直接是元。
- **场景参数**：到店自取 `beType=1` / `orderType=1` / **不传 `beCode`**（传了会报错）；得来速 `beType=5`、麦乐送 `beType=2` 需必传 `beCode`。
- **套餐拆解口径**：每轮取 `isDefault=1` 的默认项；套餐热量 = 默认组件热量之和；套餐价 = 菜单 `currentPrice`，替换组件时再加/减 `diffPrice`。
- **组餐多个默认项**：实测存在一轮里标记两个 `isDefault=1` 的情况，取第一个，其余视为同价可替换项。
- **下单确认**：`create-order` 是真实消费动作，项目约束为「未经用户明确确认绝不调用」，且**下单前必须先确认用户选的是哪一档**。
- **取餐方式**：到店下单必须传 `takeWayCode`，取值来自 `calculate-price` 返回的 `takeWayList[].code`。**各门店取值不一致**（实测见过 `eat-in` / `locker-out` / `take-in-store`），一律以当次返回为准。
- **套餐下单要传 `roundList`**：点套餐时 `items[]` 需带 `roundList`，每项形如 `{round, comboItemList:[{code, quantity}]}`，`round` 传 `query-meal-detail` 的 `rounds[].id`（**字符串形式**）。该格式已实测跑通。
- **特调 `modification` 默认不传**：用户未改特调时，组件用默认值即可（实测不传能正常下单）；仅当特调选项带 `unselectedKey` 时才需整组传入。
