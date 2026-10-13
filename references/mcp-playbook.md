# 麦当劳 MCP 工具手册（实测版）

所有调用都通过 `mcd-mcp`（`https://mcp.mcd.cn`，Bearer Token 鉴权）。本文件记录**实测过的字段与坑**，不是官方文档的复制。

## 场景参数速查

| 场景 | beType | orderType | beCode |
|---|---|---|---|
| 到店自取 | 1 | 1 | **不传**（传了会报错） |
| 得来速 DT | 5 | 1 | 必传（来自 `query-nearby-stores`） |
| 麦乐送 | 2 | 2 | 必传（来自 `delivery-query-stores`） |
| 企业团餐 | 6 | 2 | 必传（来自 `delivery-query-stores`） |

**第一版只需支持「到店自取」**，链路最短。

## 1. `query-nearby-stores`（到店/得来速门店）

- `searchType=1` 搜收藏门店，**未收藏会返回失败**：`{"success":false,"code":600050,"message":"收藏餐厅列表为空..."}`
- `searchType=2` 按位置搜，必须传 `city` + `keyword`
- 返回 `storeCode`（数字字符串，如 `1420762`）。到店自取 `beCode` 为空。

## 2. `query-meals`（菜单）

- 入参：`storeCode` + `orderType` + `beType`
- 返回结构分两块：
  - `data.categories[].meals[]`：按分类列出的 `code` + `tags`（`tags` 里会出现"套餐 / 立省10.5元起 / 爆款 / 超值"等有用标签）
  - `data.meals.<code>`：`name` / `currentPrice`（**元，字符串**）/ `originalPrice`（划线价）/ `discountType` / `canWithOrder` / `withOrder`
- ⚠️ **菜单里已经带了价格**，可以直接用来初筛，不必先算价。
- ⚠️ 菜单名可能是简称（如 `薯条`），与营养表名（`中薯条`）不一致 → 交给 `scripts/optimize.py` 归一化。
- ⚠️ **套餐的划线价 `originalPrice` 就是"单点合计价"**，可直接当作"省了多少钱"的参照（如 `精选单人餐三件套` 现价 34.5 / 划线 46）。
- `discountType` 提示该商品当前享受什么优惠（早餐卡 / 促销 / 麦金卡 / 随单购）。随单购商品必须选了随单购才能享优惠价。
- `withOrder` 非空表示该商品是"随单购"商品，享受优惠价的前提是同时购买会员卡。

## 3. `list-nutrition-foods`（营养表）

- 无入参，一次返回全部（实测 160 条），格式是**类 CSV 文本**而非标准 JSON 数组：
  ```
  猪柳麦满分,null,1288,308,16,16,24,781,213
  ```
  列顺序：`productName, nutritionDescription, energyKj, energyKcal, protein, fat, carbohydrate, sodium, calcium`
- ⚠️ **只有常见单品**：没有套餐（三件套/四件套）、没有新品、没有酱料、没有部分特调饮品（如"可乐麦炫酷""迷你草莓新地""鲜萃冰咖"）。匹配不上属正常，**如实标注，不要猜**。
- ⚠️ 名称有全半角差异（`纯牛奶（盒装）` vs `纯牛奶(盒装)`），引擎已做归一化。
- ⚠️ 同名条目可能重复（如 `小杯玉米杯`），取第一条即可。

## 4. `query-meal-detail`（套餐拆解 / 特调）★ 本项目关键工具

- 入参：`storeCode` + `orderType` + `beType` + `code`（餐品码）
- 返回 `data.rounds[]`（选配轮次列表），每轮：
  - `name`：轮次名，如"主食任意选"、"选择套餐内小食"、"选择套餐内饮料"、"蓝区"、"粉区"
  - `minQuantity` / `maxQuantity` / `quantity`：该轮最少/最多/已选数量
  - `choices[]`：该轮可选项，每项有 `code` / `name` / `isDefault`（是否默认选中）/ `diffPrice`（**与默认项的差价**，形如 `"+ ¥2"`、`"- ¥0.5"`）/ `supportModify`
- **拆解口径（本项目采用）**：
  1. 每轮取 `isDefault=1` 的项作为默认组件；
  2. 套餐热量 = 各轮默认组件热量之和（组件热量按**组件名**查营养表）；
  3. 套餐价 = 菜单给的 `currentPrice`；若替换了组件，再加/减对应 `diffPrice`。
- ⚠️ **有些轮次会有多个 `isDefault=1`**（实测 `精选超值随心配` 粉区同时标记两项默认）。取第一个即可，其余视为同价可替换项。
- ⚠️ **默认组件可能没有营养数据**（实测 `人气经典随心配` 默认饮料为"可乐麦炫酷"，营养表无此条）。此时在同一轮里改选"**有营养数据、与默认项名称最像、且差价接近最低**"的项（实测会换回"可乐中杯"，而不是柠檬茶——避免"可乐被换掉"这种观感很怪的替换），并把替换记录在 `substituted`，同时标记 `price_estimated=true`，提醒第 5 步复价。
- ⚠️ 若某轮**全部选项**都没有营养数据，则该套餐整体判为未匹配（不猜），原因写入 `unmatched`。
- `supportModify=true` 的商品支持特调；特调项若带 `unselectedKey`，算价/下单时该组所有项都要传（选中的传 `selectedKey`，未选中的传 `unselectedKey`）。**只有用户主动问时才展开特调选项。**

## 5. `calculate-price`（算价，含券）

- 入参：`storeCode` / `orderType` / `beType` / `items[]`
- `items[]`：`productCode` + `quantity`（+ `couponId`/`couponCode`）
- ✅ 实测：**套餐也能直接算价**——`items=[{productCode:"9900013304", quantity:1}]` 返回 `price: 1490`（14.9 元）。
- **返回价格单位是「分」**，展示前 `/100`。
  实测：`巨无霸 + 可乐 + 中薯条` → `price: 4850`（= 48.5 元），`productOriginalPrice: 4850`，`discount: 0`
- 返回 `takeWayList[]`：下单要用的 `takeWayCode` 从这里取。
  ⚠️ **code 不固定**：深圳店实测 `eat-in`（堂食）/ `locker-out`（外带柜），广州华夏路店实测 `eat-in` / `take-in-store`（店内自提）。**一律以当次返回为准，不要硬编码**。
- 返回 `enjoyed` / `enjoyable`：已享受 / 可享受的优惠（`amountType` 1 特价 2 折扣 3 立减；`balance` 是门槛差额，单位分）。

## 6. 优惠券三兄弟（本项目唯一的优惠来源）

| 工具 | 口径 | 用途 |
|---|---|---|
| `available-coupons` | 当前**可领取**的麦麦省券 | 告诉用户"能领什么" |
| `query-my-coupons` | 用户**卡包已有**的券 | ❗不校验门店/渠道，不代表能用 |
| `query-store-coupons` | **指定门店 + 渠道**真正可用 | ✅ 下单前必须用它复核 |

- `auto-bind-coupons`：一键领取全部可领券。**会修改用户账户，必须先征得同意。**
- `query-store-coupons` 返回 `data[].title` / `couponId` / `couponCode` / `tradeDateTime` / `products[].productCode`。同一 `couponId` 可能对应多个 `couponCode`。
- 实测：该账号在 `1420762` 门店返回 `data: []`（无可用券），属正常。

> **本项目不使用积分抵扣。** 麦当劳 MCP 的 `calculate-price` 没有"积分抵扣"参数，积分也不能直接抵现；要抵扣只能走"积分商城兑换餐品券 → 券用于订单"这条重链路，场景与"卡路里省钱"主题相关性低，故**显式排除**。用户主动问起积分时，一句话带过即可。

## 7. 下单（★ 已实跑验证）

- `create-order`：`storeCode` + `orderType` + `beType` + `items[]`
  - 到店场景**必传 `takeWayCode`**（来自 `calculate-price` 的 `takeWayList[].code`）
  - 外送场景传 `addressId` + `beCode`（+ 可选 `remark`，≤50 字）
  - **套餐必须传 `roundList`**：`[{round, comboItemList:[{code, quantity}]}]`
    - `round` = `query-meal-detail` 返回的 `rounds[].id`，**传字符串**（实测 `"1"` / `"2"` 均可用）✅
    - `comboItemList[].code` = 该轮选中组件的 `code`
  - `modification`：默认**不传**即可（实测不传可正常下单）。只有带 `unselectedKey` 的特调组才必须整组传入。
  - `needTableware`：选填，到店自取默认 `false`。
- ✅ **实测成功样例**（2026-10-13 · 广州华夏路店 `1400205`）：

  ```json
  {
    "storeCode": "1400205", "orderType": 1, "beType": 1,
    "takeWayCode": "take-in-store",
    "items": [{
      "productCode": "9900015568", "quantity": 1,
      "roundList": [
        {"round": "1", "comboItemList": [{"code": "521156", "quantity": 1}]},
        {"round": "2", "comboItemList": [{"code": "515281", "quantity": 1}]}
      ]
    }]
  }
  ```

  → 返回 `orderId` / `payId` / `payH5Url`；`orderDetail.realTotalAmount="13.9"`、`takeWay="外带"`、`comboItemList` 正确回显两个子项。
- **返回要点**：`orderId`、`payId`、`payH5Url`（支付链接）、`orderDetail.expirePayTime`（**实测约 15 分钟后过期**）、`pickupCode` / `lockerCode`（取餐码，支付后才生成）。
- 状态字段：**一律以 `orderStatus` 的中文文案为准**。`status` 的数字码与官方文档口径对不上——实测「待支付」`status="10"`、「订单已取消」`status="60"`（文档却写 10=餐厅确认配餐中、7=已取消）。**不要用 `status` 做判断。**
- ✅ 状态查询实测（2026-10-13）：`create-order` 后 `query-order` 返回「待支付」；用户取消后再查返回「订单已取消」——链路正常。
- 支付后 `query-order` 查状态；`cancel-order` 取消。
- ⚠️ **`create-order` 是真实消费动作**，未经用户明确确认绝不能调用；**且下单前必须先确认用户选的是哪一档**。

## 8. 其他

- `now-time-info`：拿服务器时间（判断券是否过期、是否在营业时段）。
- `campaign-calendar`：当月营销活动日历。
