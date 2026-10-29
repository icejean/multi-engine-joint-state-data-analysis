# dataai-test 基准失败根因分析

> 配套 `exp-report-sql-metadata-gradient.md`（实验报告）。本文件补足报告缺失的「错误根因」部分：错的都是什么题、数据字典（M1）和 ER 图（M2）各自救回了哪类错误。
>
> 数据来源：3 模型 × M/S 完整矩阵（DSH agent 跑 M、single-shot 直连跑 S），统一 deepseek-v4-flash / pro / glm-5.2。方法见文末附录。

## 摘要

1. **M0 的错误几乎全是「ref 字段歧义」**——库把外键列混淆成无语义的 `ref1/ref2/ref3`，agent 没有字典/ER 时只能靠数据分布猜「哪个 ref 是付款方/出演者」，猜错率极高。
2. **数据字典（M1）的价值 = 消除 ref 字段歧义**：`sys_table_fields.field_desc` 把 `ref1` 翻译成「出演者 ID」，M0 里 8 个 ref 猜错题在 M1 全部答对。
3. **ER 图（M2）的增量只有 1 题/模型（4%）**，且真正的贡献是「字典给不了的表间关联路径」——只有 2 题（B1、Q39）是 ref 关联猜错、靠 ER 图救回；另有 1 题（B5）是超时波动，不是 ER 的功劳。
4. **诚实边界**：M 系列是单次跑，有 ±20pp 方差（glm-5.2 M0 两次 56↔80 是实锤）；下方数字讲方向，不讲精确点估计。

---

## 1. 完整矩阵（回顾）

| 模型 | M0 | M1 | M2 | S0 | S1 | S2 |
|---|---|---|---|---|---|---|
| deepseek-v4-flash | 84% | 96% | 96% | 72% | 76% | 92% |
| deepseek-v4-pro | 80% | 96% | 100% | 68% | 72% | 96% |
| glm-5.2 | 80% | 96% | 100% | 72% | 76% | 100% |

- 三模型 M0 平均 ≈ 81%，M1 = 96%，M2 ≈ 99%。
- **M0→M1 提升 ≈ +15pp（数据字典）**；**M1→M2 提升 ≈ +3pp（ER 图）**。

---

## 2. M0 的错误根因：ref 字段歧义

M0 档（裸 schema，无字典无 ER）共有 10 题出现过模型答错，按根因分四类：

| 根因 | 题 | 说明 |
|---|---|---|
| **ref 字段语义猜错** | F1、F2、G1（dict）；C3、C6、G2、Q41、B1（join） | 8 题，占比最高 |
| **关系路径猜错** | E3（rule） | pymt→card→cust 的 id 偏移猜错 |
| **超时（探索过度）** | pro 的 E3/F1/F2、flash 的 F1 | 探索到 270s 超时，final_sql 为空 |
| **GROUP BY 答题** | H6（single） | 答案对、但 SQL 是 `GROUP BY` 而非精确 `WHERE` |

**ref 字段歧义是 M0 失败的绝对主因**（8/10）。代表例：

- **C6**（电影 ACADEMY DINOSAUR 的演员，join34）：M0 全档三模型全错（0/3）。
  - 错：`JOIN flm_act fa ON a.actr_id = fa.ref2`（ref2 是电影 ID，猜反）
  - 对：`ON a.actr_id = fa.ref1`（ref1 才是出演者 ID）
- **Q41**（doc 覆盖电影总片长，join2）：
  - 错：`JOIN film f ON d.hdng = f.ttl`（用**片名文本匹配**去关联，而不是主键）
  - 对：`ON d.doc_id = f.flm_id`
- **F1**（pymt 付款方，dict）：M0 下 agent 猜不出 `ref1/ref2/ref3` 谁是付款方，直接探索到超时。

> 根因本质：M0 的库把外键列系统性地混淆成 `ref<N>`，抹掉了字段的业务语义。agent 在无任何元数据时，唯一手段是「看数据分布猜」（`SHOW CREATE TABLE` + `MIN/MAX/COUNT DISTINCT` 试探），而 ref 列的值域高度重叠，猜错率天然高。

---

## 3. M0→M1：数据字典发挥了什么作用

字典（`sys_tables.table_desc` + `sys_table_fields.field_desc`）的作用就一句话：**把 `ref1` 翻译成「出演者 ID」**。

M0 里 8 个 ref 猜错题，在 M1 全部答对（M1 这三题通过数 3/3）。对比同一模型同一题的 M0/M1 SQL：

| 题 | M0（错） | M1（对） |
|---|---|---|
| C6 | `fa.ref2`（猜反） | `fa.ref1`（field_desc 标「出演者 ID」） |
| Q41 | `d.hdng = f.ttl`（标题匹配） | `d.doc_id = f.flm_id` |
| F1 | 超时（猜不出） | `COUNT(DISTINCT ref1)`（field_desc 标「付款方」） |

**字典的边际价值集中在「dict 类 + 简单 join 类」**：这些题只要知道 ref 列的业务含义就能答对，不需要知道表间完整关联。所以 M1 的 96% 里，dict 6/6、rule 4/4、single 2/2 全部满分，只剩 join 类的少量题。

---

## 4. M1→M2：ER 图贡献了 4%（且要打折）

M1→M2 三个模型合计多答对 3 题（B1、B5、Q39），即每模型 +1 题（4pp）。逐题看：

| 题 | M1 错因 | M2 | 是不是 ER 贡献 |
|---|---|---|---|
| B1（glm-5.2，演员出演数）| `fa.ref2` 猜反 | `fa.ref1` | ✅ **真 ER 贡献**：`sys_foreignkeys` 明确 `flm_act.ref1→actr.actr_id` |
| Q39（flash，消费最高客户城市）| `pymt.ref1 = rntl.rnt_id`（猜错关联表）| `pymt.ref1 = card.card_id` | ✅ **真 ER 贡献**：ER 图明确 `pymt.ref1→card.card_id` |
| B5（pro，客户总消费金额）| **超时**（`agent timeout`）| 正常答出 | ❌ **不是 ER 贡献**，是超时波动 |

**结论：ER 图的真实增量只有 2 题（B1、Q39）**，占 4% 差异里的 2/3；另 1/3（B5）是探索超时的随机波动，不能归功于 ER。

为什么 ER 的增量这么小？因为**字典已经覆盖了大部分 join 题**——`ref1` 标了「出演者 ID」，agent 自然知道 join `actr.actr_id`。ER 图只在「字段语义本身不足以推导关联」时才必要：B1/Q39 的共同点是 ref 列同时能对应多张表（`flm_act.ref1` 是演员还是电影？`pymt.ref1` 是 card 还是 rntl？），这时只有 ER 图能拍板。

---

## 5. 残余失败（M2 仍有 1 题）

- **F5（flash，cust 表不同归属网点数，dict）**：M2 有完整字典+ER，但 flash 仍跑成 `COUNT(*) + COUNT(DISTINCT ref1) + COUNT(DISTINCT ref2) ...` 的多列统计，而非精确 `COUNT(DISTINCT ref5)`。这是「不确定就列全」的答题习惯，不是元数据不够。

---

## 6. 结论

1. **元数据梯度的价值链条清晰且可信**：
   - **M0→M1（字典）**：消除 ref 字段歧义，+15pp，救回 8 个 ref 猜错题。
   - **M1→M2（ER）**：提供表间关联路径，+3pp，救回 2 个「字段语义不足以推断关联」的题。
2. **字典是主力，ER 是补漏**：M1 已经吃掉绝大部分元数据收益，ER 的增量是「长尾里的关联歧义题」。这个结论与「S 系列 S0→S2 梯度主要来自 ER」形成对照——**agent 靠字典就能推断大部分关联，single-shot 则必须靠注入的 ER**（详见报告机制对比段）。
3. **不能写进报告当定论的部分**：
   - M 系列单次跑方差大（±20pp），上面的数字是方向不是精确值；
   - M1→M2 的 4% 里有 1/3 是超时波动（B5），ER 的真实增量要打折；
   - M2 的 F5 失败是答题习惯，与元数据无关。

---

## 附录：方法

- **B/C 拆分**：对每个失败 run，把 `sql_history` 里每条 SQL 用 pymysql 重跑、与 gold 比对。存在能命中 gold 的 SQL（答案在中间、取最后一条取错）= B 类；没有任何 SQL 命中 = C 类（真没答对）。
- **根因分类**：对比同一模型同一题在 M0/M1/M2 的 `final_sql` 差异，人工归类为 ref 语义猜错 / 关系路径猜错 / 超时 / GROUP BY 答题。
- **数据完整性**：M 系列 agent 结果已通过「提示词修复」（抑制末尾验证 SQL）消除 87% 假阴性，B 类残余归零，见 `results_dsh_*_full.json`。
