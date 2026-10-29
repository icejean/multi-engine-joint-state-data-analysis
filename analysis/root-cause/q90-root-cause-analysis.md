# Q90 根因分析：一道「双重语义歧义 + 间接 schema」的硬骨头

> works_cycles（AdventureWorks）26 题梯度敏感子集里的 Sales 题。本文是 Q90 的独立根因分析，回答一个问题：**为什么这道题 agent 修不好、也不值得再修**。
>
> 结论先行：Q90 是 **两个独立的语义歧义** 叠加 **一个 schema 间接性**，三者都踩在同一道题上。官方 gold 本身取错了实体（把「销售员」取成「主联系人」），agent 则把「门店的 territory」当成「销售员的 territory」。即使修好 gold、消歧题面，agent 仍稳定答错——它卡在「门店没有 TerritoryID，地域要绕道 Customer 表」这个 schema 间接性上。**留作「AI 局限性」例证，比凑一个 100% 数字更有意义。**

---

## 1. 题目与现象

- **Question**（BIRD 原文）：`Name all stores and its sales representative in France territory.`
- **Evidence**（BIRD 原文）：`France territory refers to SalesTerritory.Name = 'France';`
- 属性：domain=Sales，join_count=3，features=`JOIN×3`。

同一道题，三种解释给出三个不同的答案（均实测 MySQL）：

| 解释 | 「sales representative」取谁 | 「in France」修饰谁 | 行数 |
|---|---|---|---|
| **BIRD 官方 gold** | 客户主联系人 `Customer.PersonID` | 门店 territory `Customer.TerritoryID` | **34** |
| **agent 稳定输出** | 门店销售员 `Store.SalesPersonID` | 销售员 territory `SalesPerson.TerritoryID` | **40** |
| **语义正确** | 门店销售员 `Store.SalesPersonID` | 门店 territory `Customer.TerritoryID` | **74** |

agent 在 M0/M1/M2 三档、以及把题面消歧成「stores located in the France territory, along with each store's assigned salesperson」之后，仍稳定输出 40 行（0/3 全挂）。

---

## 2. 涉及的实体与关系

AdventureWorks 里「门店 + 销售员 + 地域」横跨四张表，关系是间接的：

```
SalesTerritory (地域)
     ↑ Customer.TerritoryID            ← 门店的「地域」在这里，不在 Store 表
Customer (客户：个人或门店)
     ↑ Customer.StoreID = Store.BusinessEntityID
Store (门店) —— 没有 TerritoryID 列！
     ↑ Store.SalesPersonID
SalesPerson (销售员) —— 有自己的 TerritoryID
     ↑ SalesPerson.BusinessEntityID = Person.BusinessEntityID
Person (姓名)
```

关键 schema 事实（列名混淆后对应关系）：

| 表 | 列 | 含义 |
|---|---|---|
| Customer | `ref1` | StoreID（客户是门店时的门店 ID） |
| Customer | `ref2` | TerritoryID（客户的所在地域） |
| Customer | `ref3` | PersonID（客户是个人时 / 门店主联系人） |
| Store | `ref1` | SalesPersonID（指派给该门店的销售员） |
| Store | `ref2` | BusinessEntityID（门店主键） |
| SalesPerson | `ref1` | TerritoryID（销售员自己的地域） |
| SalesPerson | `ref2` | BusinessEntityID |

---

## 3. 两个独立的语义歧义

### 歧义一：「sales representative」指谁？

- **BIRD gold** 取 `Customer.PersonID` = 客户**主联系人**。法国门店客户 74 个里，只有 34 个同时挂了 PersonID（主联系人），所以 gold 是 34 行。
- **语义正确** 是 `Store.SalesPersonID` = 门店指派的**销售员**。74 个法国门店**全部**有 SalesPersonID。

「sales representative」（销售代表）自然指销售员，不是联系人。gold 把两个角色搞混了——**这是官方 gold 的实体取错**，和 Q95（oldest 用 HireDate 而非 evidence 的 BirthDate）同类。

### 歧义二：「in France territory」修饰谁？

- **正确**：修饰「stores」——门店**所在地域** = `Customer.TerritoryID`（因为 Store 没有 TerritoryID，门店地域只能经 Customer 间接拿）。
- **agent**：修饰「sales representative」——销售员的**自身地域** = `SalesPerson.TerritoryID`。

题干「stores … in France territory」语法上「in France」应修饰 stores，但 agent 看到 salesperson 就本能走 SalesPerson 的地域。

---

## 4. 三条 SQL（对照）

### 4.1 BIRD 官方 gold（34 行）—— 地域对，实体错

```sql
SELECT T3.Name, T4.FirstName, T4.LastName
FROM SalesTerritory AS T1
  INNER JOIN Customer AS T2 ON T1.TerritoryID = T2.TerritoryID   -- 门店地域（对）
  INNER JOIN Store     AS T3 ON T2.StoreID     = T3.BusinessEntityID
  INNER JOIN Person    AS T4 ON T2.PersonID    = T4.BusinessEntityID  -- 主联系人（错）
WHERE T1.Name = 'France'
```

### 4.2 agent 稳定输出（40 行）—— 实体对，地域错

```sql
SELECT s.Name, p.FirstName, p.LastName
FROM Store s
  JOIN SalesPerson sp ON sp.BusinessEntityID = s.SalesPersonID   -- 门店销售员（对）
  JOIN SalesTerritory t ON t.TerritoryID = sp.TerritoryID        -- 销售员地域（错）
  JOIN Person p ON p.BusinessEntityID = sp.BusinessEntityID
WHERE t.Name = 'France'
```

### 4.3 语义正确（74 行）

```sql
SELECT T3.Name, T5.FirstName, T5.LastName
FROM SalesTerritory AS T1
  INNER JOIN Customer    AS T2 ON T1.TerritoryID = T2.TerritoryID       -- 门店地域（对）
  INNER JOIN Store       AS T3 ON T2.StoreID    = T3.BusinessEntityID
  INNER JOIN SalesPerson AS T4 ON T3.SalesPersonID = T4.BusinessEntityID  -- 门店销售员（对）
  INNER JOIN Person      AS T5 ON T4.BusinessEntityID = T5.BusinessEntityID
WHERE T1.Name = 'France'
```

---

## 5. 数据验证（MySQL 实测）

| 查询口径 | 结果 |
|---|---|
| 法国客户总数（Customer.TerritoryID=France） | 1884 |
| 其中是门店的（Customer.StoreID 非空） | **74** |
| 其中是个人的（Customer.PersonID 非空） | 1844 |
| **门店且同时挂 PersonID（主联系人）** | **34** ← gold |
| 销售员地域=France 的门店数（SalesPerson.TerritoryID） | **40** ← agent |
| 法国门店数（正确口径） | **74** ← 正确 |
| 其中销售员非空的 | 74（全部有） |

三个数字 34 / 40 / 74 各自精确对应三种解释，无一是巧合。

---

## 6. 为什么「修 gold + 消歧题面」都不够

1. **修 gold**（`Customer.PersonID → Store.SalesPersonID`，34→74 行）：只修好了「sales rep 取错实体」这一半，agent 的「France 修饰错实体」仍在。
2. **题面消歧**（改成「stores located in the France territory … assigned salesperson」）：agent 仍 0/3。因为它的错误路径是 schema 层面的——看到 salesperson 就 `Store → SalesPerson → SalesPerson.TerritoryID`，它**没有「门店的地域要绕道 Customer」这个 schema 概念**。

### 根因本质

Store 表没有 TerritoryID 列，门店地域只能靠 `Customer.StoreID = Store.BusinessEntityID → Customer.TerritoryID` 间接拿到。agent 在「门店地域」和「销售员地域」之间缺了这一步间接推导，稳定地错选了销售员的地域。这不是措辞问题（题面已经消歧了），也不是元数据问题（字典/ER 都给了字段含义），而是 **LLM 对「间接 schema 路径」的推理上限**——这类题连人都要先翻 schema 才能答对。

---

## 7. 处理结论

- ✅ gold 已修（34→74 行，`question_set_final(_obfuscated).json` 的 Q90 note 留 provenance）。
- ✅ 题面已消歧。
- ❌ agent 仍 0/3（M0/M1/M2）。
- **决策：接受 Q90 为硬骨头，留作「AI 局限性」的正面例证**。对外讲法：26 题里 25 题可解，唯一解不了的是这道「双重语义歧义 + 间接 schema」的题，它恰恰说明 AI 卡在 schema 间接性上——比一个经过量身修复的 100% 数字更诚实、更有说服力。
