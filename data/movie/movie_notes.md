# movie 图库 Cypher 注意事项（M+S 资源文件 · notes）

> 本文是「写 Cypher 前的踩坑清单」。图结构（标签/属性/关系方向）以 `movie_schema.json` 为准，本文只讲规则与坑。

## 0. 重名节点（最高频坑，务必先读）

图里有**海量重名节点**（同名实体是多个不同节点，如多部重拍片都叫 "Ned Kelly"）：

| 标签 | 重名多余节点数 |
|---|---|
| Movie | 25304 |
| Person | 3859 |
| ProductionCompany | 10 |
| FilmSeries | 4 |
| Genre | 4 |
| Award | 3 |

gold 一律按**节点**去重，不是按名字去重——「列出电影名」这类题，同名电影要**各出一行**：

```cypher
// ✅ 按节点去重：同名电影各出一行
MATCH (n:Movie)-[:...]->(...) WITH DISTINCT n RETURN n.name

// ❌ 按名字去重：会把同名电影合并成一行，少行数
MATCH (n:Movie)-[:...]->(...) RETURN DISTINCT n.name
```

同理计数：`count(DISTINCT n)`（按节点），**不要** `count(DISTINCT n.name)`（按名字）。「每个/各 movie/person」= 每个节点。

**「名字 + 计数」同理（最常错）**：`RETURN n.name, count(DISTINCT m)` 会**按 name 分组**、把同名电影合并成一行并加总计数；必须按节点分组：

```cypher
// ❌ 错误：按 name 分组，同名电影合并（如 3 个 "Ned Kelly" → 1 行 count=3）
RETURN m.name, count(DISTINCT d)

// ✅ 正确：按节点分组，同名电影各出一行（3 个 "Ned Kelly" → 3 行 count=1）
WITH m, count(DISTINCT d) AS num
RETURN m.name, num
```

## 1. 稀疏属性 + NULL 排序

部分属性很多节点缺失（NULL），Neo4j 排序规则：

- `ORDER BY x DESC` → **NULL 排最前**；`ORDER BY x ASC` → NULL 排最后。

**`WHERE x IS NOT NULL` 只在「取极值」时加**（`ORDER BY x ... LIMIT 1` 问「最高/最新/最长」），否则会取到 NULL 行：

```cypher
MATCH ... WITH DISTINCT n
WHERE n.属性 IS NOT NULL        -- 只有 ORDER BY ... LIMIT 1 取极值才加
RETURN n.name ORDER BY n.属性 DESC LIMIT 1
```

**「列出所有」题不要加 `WHERE IS NOT NULL`**——NULL 也是合法值，要原样返回（例如「列出以色列电影及票房」要把票房为 NULL 的电影也列出来）。

稀疏属性清单：`global_box_office_usd`(1263/218828)、`filming_location`(19222)、`runtime_minute`(109337)、`original_language`(170487)、`date_of_death`(64221/234309)、`date_of_birth`(165357)、`place_of_birth`(169638)、`country_of_citizenship`(189340)、`gender`(222059)。只有 `name` 全覆盖。

## 2. 关系方向

所有关系都从 Movie 出发指向目标（`(Movie)-[:rel]->(target)`），方向固定：

```
(Movie)-[:hasGenre]->(Genre)          (Movie)-[:hasCastMember]->(Person)
(Movie)-[:directedBy]->(Person)       (Movie)-[:writtenBy]->(Person)
(Movie)-[:producedBy]->(ProductionCompany)   (Movie)-[:receivesAward]->(Award)
(Movie)-[:releasedIn]->(Country)      (Movie)-[:originatesFrom]->(Country)
(Movie)-[:partOfSeries]->(FilmSeries)
```

方向反了（`<-`）会得到空集或漏结果。多跳时留意中间节点方向，如「某导演导过哪些片」=`(p:Person)<-[:directedBy]-(:Movie)-[:writtenBy]->(p)`。

## 3. 同一节点约束（「既 A 又 B」）

题面说「**既** A **又** B（同一个 X）」时，两个条件必须用**同一个变量**：

```cypher
// ✅ 同一个 movie：既被某人导演、又由某人主演
MATCH (m:Movie)-[:directedBy]->(p:Person), (m)-[:hasCastMember]->(p)

// ❌ 两个不同变量：变成「演过一部、导过另一部」
MATCH (m1:Movie)-[:directedBy]->(p), (m2:Movie)-[:hasCastMember]->(p)
```

常见题：既演又导、既写又演、既导又写——都是同一个 movie + 同一个 person。

## 4. 比较题输出形状（「Which / Are ... same」）

这类题返回**单个答案**，不是两个实体各自的值：

```cypher
// ✅ Which is longer / higher → CASE 返回一个名字
RETURN CASE WHEN a.runtime_minute > b.runtime_minute THEN 'A' ELSE 'B' END

// ✅ Are they same → 返回一个布尔
RETURN a.country = b.country AS answer

// ❌ 不要返回两个实体各自的值并列（gold 是单值）
```

## 5. 枚举值措辞（genre 值命名不统一）

genre 的 name 值**不统一**——有的短、有的带 ` film` 后缀，且两者可能同时存在、规模差巨大：

- `"thriller"`(146 部) vs `"thriller film"`(6275 部)
- `"fantasy"`(18 部) vs `"fantasy film"`(3028 部)
- `"science fiction"` vs `"science fiction film"`

**没有可套的规则**（有的题用短形式、有的用长形式）。所以凡涉及 genre 值，**必须 `preview_data` 查 Genre 的 name 实际取值**——题面的口语词（"thriller films" / "fantasy films"）到底对应哪个值，以查到的为准，别猜、别套「带 film 后缀」之类的规则。

## 6. fan-out 去重

一对多（一个节点连多个邻居）时，问「有哪些 X」加 `WITH DISTINCT n`（按节点），问「数量」用 `count(DISTINCT n)`。去重对象是实体节点，不是返回值。

## 7. 聚合口径

- 平均 = `avg(x)`；计数 = `count(x)` / `count(DISTINCT x)`。
- Cypher 无 GROUP BY：聚合前用 `WITH` 分组——**按节点分组**：`WITH n, count(DISTINCT m) AS num RETURN n.name, num`。
- `RETURN n.name, count(...)` 会**按 name 分组**（把同名节点合并），务必用 `WITH n, count(...) ... RETURN n.name, ...` 按节点分组。
- **计数去重**：问「有多少 X」用 `count(DISTINCT x)`，**不要 `count(*)`**——`count(*)` 会把一对多（同一 X 对应多行）重复计数。
- **保留 0 关联**：问「每个 X 有几个 Y」时，X 可能没有 Y（0 个）。用 `OPTIONAL MATCH (x)-[:r]->(y)` 保留 0 个 Y 的 X；普通 `MATCH` 会**丢掉**没有 Y 的 X。

## 8. 属性类型与其它

- `original_language` / `filming_location` / `country_of_citizenship` 是 **List**（数组）；`runtime_minute`/`global_box_office_usd` 是 Float；`date_of_birth`/`date_of_death` 是 Date 字符串 `YYYY-MM-DD`。
- 题面问「名字/名称」→ 返回 `name` 属性，不要返回 elementId/内部 id。
- `over/more than N` = `> N`；`at least N` = `>= N`。
- 一次 `run_code` 一条 Cypher；最终答案 = 最后一条 Cypher，必须直接 RETURN 题面要的字段，不要停在 `CALL db.labels()` / `preview_data` 上。

## 9. 不要硬编码「推导值」

题面给出的实体（电影名/人名），要用 Cypher **从该实体推导**关联值，不要把你 preview 到的中间值写死进 WHERE：

```cypher
// ✅ 先 MATCH 出 The Fighter 的 releasedIn 国家，再 MATCH 同国电影
MATCH (f:Movie {name:'The Fighter'})-[:releasedIn]->(c:Country)
MATCH (m:Movie)-[:originatesFrom]->(c)

// ❌ 硬编码：把 preview 到的 "Germany" 写死（万一 The Fighter 不止一个、或国家名不同就错）
MATCH (m:Movie)-[:releasedIn]->(:Country {name:'Germany'})
```

## 10. 「电影产自/来自某国」用 originatesFrom

- 「电影来自/产自/来自哪个国家」= `originatesFrom`（电影的来源国，Movie→Country）。
- `producedBy`（Movie→ProductionCompany）是「制片公司」，**不是**产地——题面说「produced in a country」指产地时，用 `originatesFrom` 而非 `producedBy` 的公司所在地。
- `releasedIn` = 上映国家，`originatesFrom` = 产地，两者可能不同。
