# 元数据梯度实验题库 · 最终 25 题

> 本文件是**最终定稿的 25 道题**的人读版；机器可读的单一事实来源是 [`questions.json`](./questions.json)。
> 判分 = 执行准确率 EX（结果集比对，gold 见 `gold.json`）。三档库 `sakila_rntl` / `sakila_rntl_m1` / `sakila_rntl_meta` 数据一致。
> 题号与 `questions.json` 的 `id` 一一对应；`hop` = JOIN 跳数。

## 题型分布

| 类别 | 题数 | 题号 |
|---|---|---|
| 单表（对照/自检） | 2 | A3、H6 |
| 字典·语义化外键列 | 6 | F1–F5、G1 |
| 字典·缩写列名 | 1 | D1 |
| 两表 JOIN（2 跳） | 6 | B1、G2、H1、H2、H4、Q41 |
| 多表 JOIN（3–5 跳） | 6 | B5、C3、C5、C6、H3、Q39 |
| 隐含业务规则 | 4 | E2、E3、H5、Q40 |

---

## 一、单表（对照/自检）

### A3
分级为 PG-13 的电影有多少部？
```sql
SELECT COUNT(*) AS n FROM film WHERE rtng = 'PG-13'
```

### H6
有多少张付款卡处于封卡（blocked）状态？
```sql
SELECT COUNT(*) AS n FROM card WHERE sts = 'blocked'
```

---

## 二、字典·语义化外键列（`ref<N>` 映射回业务角色）

### F1
pymt 表里一共有多少个不同的付款方？
```sql
SELECT COUNT(DISTINCT ref1) AS n FROM pymt
```

### F2
pymt 表里一共有多少个不同的经办人？
```sql
SELECT COUNT(DISTINCT ref2) AS n FROM pymt
```

### F3
rntl 表里一共有多少个不同的租借方？
```sql
SELECT COUNT(DISTINCT ref2) AS n FROM rntl
```

### F4
rntl 表里一共有多少个不同的经办人？
```sql
SELECT COUNT(DISTINCT ref3) AS n FROM rntl
```

### F5
cust 表里一共有多少个不同的归属网点？
```sql
SELECT COUNT(DISTINCT ref1) AS n FROM cust
```

### G1
awd 表里一共有多少个不同的获奖出演者？
```sql
SELECT COUNT(DISTINCT ref1) AS n FROM awd
```

---

## 三、字典·缩写列名

### D1
可以租借 7 天的电影有多少部？
```sql
SELECT COUNT(*) AS n FROM film WHERE rnt_dur = 7
```

---

## 四、两表 JOIN（2 跳）

### B1
每位演员出演过多少部电影？只返回名、姓、出演数三列，按出演数降序、名升序、姓升序取前 10。
```sql
SELECT a.frst_nm, a.last_nm, COUNT(fa.ref2) AS n
FROM actr a JOIN flm_act fa ON a.actr_id = fa.ref1
GROUP BY a.actr_id, a.frst_nm, a.last_nm
ORDER BY n DESC, a.frst_nm ASC, a.last_nm ASC
LIMIT 10
```

### G2
获奖最多的 3 位演员分别是谁？只返回名、姓、获奖数三列，按获奖数降序、名升序、姓升序。
```sql
SELECT a.frst_nm, a.last_nm, COUNT(*) AS n
FROM awd w JOIN actr a ON w.ref1 = a.actr_id
GROUP BY a.actr_id, a.frst_nm, a.last_nm
ORDER BY n DESC, a.frst_nm ASC, a.last_nm ASC
LIMIT 3
```

### H1
用虚拟卡付款的客户有多少位？
```sql
SELECT COUNT(DISTINCT cd.ref1) AS n
FROM pymt p JOIN card cd ON p.ref1 = cd.card_id
WHERE cd.crd_typ = '虚拟卡'
```

### H2
用封卡（blocked）状态付款的客户有多少位？
```sql
SELECT COUNT(DISTINCT cd.ref1) AS n
FROM pymt p JOIN card cd ON p.ref1 = cd.card_id
WHERE cd.sts = 'blocked'
```

### H4
每位客户拥有的付款卡数量是多少？只返回名、姓、卡数三列，按卡数降序、名升序、姓升序取前 10。
```sql
SELECT c.frst_nm, c.last_nm, COUNT(cd.card_id) AS n
FROM cust c JOIN card cd ON c.cust_id = cd.ref1
GROUP BY c.cust_id, c.frst_nm, c.last_nm
ORDER BY n DESC, c.frst_nm ASC, c.last_nm ASC
LIMIT 10
```

### Q41
doc 表覆盖的电影，总片长是多少分钟？只返回一个数值。
```sql
SELECT SUM(f.lngth) FROM doc d JOIN film f ON d.doc_id = f.flm_id
```

---

## 五、多表 JOIN（3–5 跳）

### B5（3 跳）
每位客户的总消费金额是多少？只返回名、姓、金额三列，按金额降序、名升序、姓升序取前 10。
```sql
SELECT c.frst_nm, c.last_nm, SUM(p.amt) AS total
FROM pymt p JOIN card cd ON p.ref1 = cd.card_id
JOIN cust c ON cd.ref1 = c.cust_id
GROUP BY c.cust_id, c.frst_nm, c.last_nm
ORDER BY total DESC, c.frst_nm ASC, c.last_nm ASC
LIMIT 10
```

### C3（4 跳）
客户 MARY SMITH 一共租过多少部不同的电影？
```sql
SELECT COUNT(DISTINCT f.flm_id) AS n
FROM cust c JOIN rntl r ON c.cust_id = r.ref2
JOIN invt i ON r.ref1 = i.invt_id
JOIN film f ON i.ref1 = f.flm_id
WHERE c.frst_nm = 'MARY' AND c.last_nm = 'SMITH'
```

### C5（3 跳）
喜剧（Comedy）分类下一共有多少部电影？
```sql
SELECT COUNT(*) AS n
FROM film f JOIN flm_cat fc ON f.flm_id = fc.ref1
JOIN catg c ON fc.ref2 = c.catg_id
WHERE c.nm = 'Comedy'
```

### C6（3 跳）
电影 ACADEMY DINOSAUR 有哪些演员？只返回名、姓两列，按名升序、姓升序。
```sql
SELECT a.frst_nm, a.last_nm
FROM film f JOIN flm_act fa ON f.flm_id = fa.ref2
JOIN actr a ON fa.ref1 = a.actr_id
WHERE f.ttl = 'ACADEMY DINOSAUR'
ORDER BY a.frst_nm ASC, a.last_nm ASC
```

### H3（3 跳）
每位客户用过的付款卡数量是多少？只返回名、姓、卡数三列，按卡数降序、名升序、姓升序取前 10。
```sql
SELECT c.frst_nm, c.last_nm, COUNT(DISTINCT cd.card_id) AS n
FROM pymt p JOIN card cd ON p.ref1 = cd.card_id
JOIN cust c ON cd.ref1 = c.cust_id
GROUP BY c.cust_id, c.frst_nm, c.last_nm
ORDER BY n DESC, c.frst_nm ASC, c.last_nm ASC
LIMIT 10
```

### Q39（5 跳 + 子查询）
消费总额最高的客户，住在哪个城市？只返回城市名一列。
```sql
SELECT ci.cty
FROM cust c JOIN addr a ON c.ref2 = a.addr_id
JOIN city ci ON a.ref1 = ci.cty_id
WHERE c.cust_id = (
  SELECT cd.ref1 FROM pymt p JOIN card cd ON p.ref1 = cd.card_id
  GROUP BY cd.ref1 ORDER BY SUM(p.amt) DESC LIMIT 1
)
```

---

## 六、隐含业务规则

### E2
目前活跃的客户有多少位？
```sql
SELECT COUNT(*) AS n FROM cust WHERE actv = 1
```

### E3（2 跳）
消费总额超过 150 元的客户有多少位？
```sql
SELECT COUNT(*) AS n
FROM (
  SELECT cd.ref1 FROM pymt p JOIN card cd ON p.ref1 = cd.card_id
  GROUP BY cd.ref1 HAVING SUM(p.amt) > 150
) t
```

### H5
有多少位客户拥有超过一张付款卡？
```sql
SELECT COUNT(*) AS n
FROM (SELECT ref1 FROM card GROUP BY ref1 HAVING COUNT(*) > 1) t
```

### Q40
有多少张付款卡从未被任何付款使用过？
```sql
SELECT COUNT(*) AS n FROM card WHERE card_id NOT IN (SELECT DISTINCT ref1 FROM pymt)
```
