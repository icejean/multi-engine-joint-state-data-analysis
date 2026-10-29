#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建 DataAI Portal v0.8.0 元数据梯度实验的改名版 sakila 库。

产物:
  1. `sakila_rntl`      —— 半可读缩写命名的 18 张数据表(原 sakila 16 表改名 + 合成 card/awd),无外键约束、无二级索引、无 sys 表(M0)
  2. `sakila_rntl_m1`   —— 同数据 + sys_tables / sys_table_fields 字典两表,无 ER(M1)
  3. `sakila_rntl_meta` —— 同数据 + sys_tables / sys_table_fields / sys_foreignkeys 三张元数据表(M2)
  4. `dataai-test/data/sakila/rename_map.json` —— 改名映射(供 gold 翻译使用)

设计要点(见 docs/exp-metadata-gradient.md):
  - 命名 = 半可读缩写(非 sakila 原名,亦非无语义标识符)
  - M0 不含外键约束/二级索引 —— 现代数仓普遍不建外键,关系信息缺失正是被测变量
  - sys_foreignkeys 用 constraint_name 分组以支持复合外键
  - sys_tables 带 table_type(fact/dim/junction)
"""
import json
import os
import re

import pymysql

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_MAP = os.path.join(SCRIPT_DIR, "..", "data", "sakila", "rename_map.json")

SRC_DB = "sakila"
DB_M0 = "sakila_rntl"          # 数据表,无 sys 表
DB_M1 = "sakila_rntl_m1"       # 数据表 + 字典两表(sys_tables/sys_table_fields),无 ER
DB_M2 = "sakila_rntl_meta"     # 数据表 + 完整三张 sys 表

# 合成获奖数据(awd 表):前 6 个 distinct 演员,演员 i 获 (7-i) 个奖(取它最早的前 (7-i) 部影片)
AWARD_ACTORS = 6
AWARD_NAMES = ["最佳男主角", "最佳女主角", "最佳男配角", "最佳女配角", "最佳群演", "评审团特别奖"]

# awd 表列定义(该表不在原始 sakila 里,类型手工指定,对齐 film_actor 的 actor_id/film_id)
_AWD_COLUMNS = {
    "award_id": ("int", "NO", "PRI", None, "auto_increment"),
    "actor_id": ("smallint unsigned", "NO", "", None, ""),
    "film_id": ("smallint unsigned", "NO", "", None, ""),
    "award_name": ("varchar(50)", "NO", "", None, ""),
    "award_year": ("year", "NO", "", None, ""),
}

# card 表列定义(同样不在原始 sakila 里,合成数据)。业务意义见 docs/exp-metadata-gradient.md:
#   「付款账户/卡」—— 一个客户可持多张卡(换卡/虚拟卡短有效期/封卡段),payment 事实引用的是「卡」而非「人」。
#   card_id 取值域刻意从 1001 起(与 cust_id 1..599 不重叠),使 M1 猜错表时 join 到空集。
_CARD_COLUMNS = {
    "card_id": ("int", "NO", "PRI", None, "auto_increment"),
    "cust_id": ("smallint unsigned", "NO", "", None, ""),
    "card_type": ("varchar(20)", "NO", "", None, ""),
    "card_last4": ("varchar(4)", "NO", "", None, ""),
    "valid_to": ("date", "NO", "", None, ""),
    "status": ("varchar(16)", "NO", "", None, ""),
    "open_dt": ("date", "NO", "", None, ""),
}


def _load_creds():
    """读取 MYSQL* 凭据:本地 .env 优先(开源复现),回退 Portal 模板路径(本机开发)。"""
    local = os.path.join(SCRIPT_DIR, "..", ".env")
    env_path = local if os.path.exists(local) else "/opt/dataai/templates/.env"
    creds = {}
    with open(env_path) as f:
        for line in f:
            m = re.match(r"^\s*(MYSQLHOST|MYSQLPORT|MYSQLUSER|MYSQLPASSWORD)\s*=\s*(.*)\s*$", line)
            if m:
                creds[m.group(1)] = m.group(2)
    return creds


# ---- 改名映射 + 业务描述(单一事实来源) -------------------------------------
# 每表: orig -> (new_name, table_type, table_desc, [(orig_col, new_col, field_desc), ...])
# 列顺序与 information_schema 的 ordinal_position 保持一致。
TABLES = {
    "actor": ("actr", "dim", "演员维度表,每行一名演员", [
        ("actor_id", "actr_id", "演员ID(主键)"),
        ("first_name", "frst_nm", "名"),
        ("last_name", "last_nm", "姓"),
        ("last_update", "lst_upd", "最后更新时间"),
    ]),
    "address": ("addr", "dim", "地址维度表,客户/员工/门店的住址", [
        ("address_id", "addr_id", "地址ID(主键)"),
        ("address", "addr", "街道地址"),
        ("address2", "addr2", "地址第二行(可空)"),
        ("district", "dist", "区/地区"),
        ("city_id", "cty_id", "所属城市ID"),
        ("postal_code", "pst_cd", "邮政编码"),
        ("phone", "phn", "联系电话"),
        ("location", "loc", "地理坐标(geometry)"),
        ("last_update", "lst_upd", "最后更新时间"),
    ]),
    "category": ("catg", "dim", "影片分类维度表", [
        ("category_id", "catg_id", "分类ID(主键)"),
        ("name", "nm", "分类名称"),
        ("last_update", "lst_upd", "最后更新时间"),
    ]),
    "city": ("city", "dim", "城市维度表", [
        ("city_id", "cty_id", "城市ID(主键)"),
        ("city", "cty", "城市名称"),
        ("country_id", "cnty_id", "所属国家ID"),
        ("last_update", "lst_upd", "最后更新时间"),
    ]),
    "country": ("cnty", "dim", "国家维度表", [
        ("country_id", "cnty_id", "国家ID(主键)"),
        ("country", "cntry", "国家名称"),
        ("last_update", "lst_upd", "最后更新时间"),
    ]),
    "customer": ("cust", "dim", "客户维度表", [
        ("customer_id", "cust_id", "客户ID(主键)"),
        ("store_id", "stor_id", "所属门店ID"),
        ("first_name", "frst_nm", "名"),
        ("last_name", "last_nm", "姓"),
        ("email", "eml", "电子邮箱"),
        ("address_id", "addr_id", "住址ID"),
        ("active", "actv", "是否活跃(1=是,0=否)"),
        ("create_date", "crt_dt", "建档日期"),
        ("last_update", "lst_upd", "最后更新时间"),
    ]),
    "film": ("film", "fact", "影片主表,含影片属性与租借定价", [
        ("film_id", "flm_id", "影片ID(主键)"),
        ("title", "ttl", "片名"),
        ("description", "dsc", "剧情简介"),
        ("release_year", "rls_yr", "发行年份"),
        ("language_id", "lang_id", "主语言ID"),
        ("original_language_id", "orig_lang_id", "原始语言ID(可空)"),
        ("rental_duration", "rnt_dur", "可租借天数"),
        ("rental_rate", "rnt_rate", "租金单价"),
        ("length", "lngth", "片长(分钟)"),
        ("replacement_cost", "rplc_cst", "替换成本"),
        ("rating", "rtng", "分级(G/PG/PG-13/R/NC-17)"),
        ("special_features", "spcl_ftr", "附加特性(Trailers/Commentaries/Deleted Scenes/Behind the Scenes)"),
        ("last_update", "lst_upd", "最后更新时间"),
    ]),
    "film_actor": ("flm_act", "junction", "影片-演员关联表(多对多)", [
        ("actor_id", "actr_id", "演员ID"),
        ("film_id", "flm_id", "影片ID"),
        ("last_update", "lst_upd", "最后更新时间"),
    ]),
    "film_category": ("flm_cat", "junction", "影片-分类关联表(多对多)", [
        ("film_id", "flm_id", "影片ID"),
        ("category_id", "catg_id", "分类ID"),
        ("last_update", "lst_upd", "最后更新时间"),
    ]),
    "film_text": ("doc", "dim", "文档表,全文检索索引", [
        ("film_id", "doc_id", "文档ID(主键)"),
        ("title", "hdng", "文档标题"),
        ("description", "body", "正文"),
    ]),
    "inventory": ("invt", "fact", "库存表,每个可出租的影片副本一行", [
        ("inventory_id", "invt_id", "库存ID(主键)"),
        ("film_id", "flm_id", "影片ID"),
        ("store_id", "stor_id", "所属门店ID"),
        ("last_update", "lst_upd", "最后更新时间"),
    ]),
    "language": ("lang", "dim", "语言维度表", [
        ("language_id", "lang_id", "语言ID(主键)"),
        ("name", "nm", "语言名称"),
        ("last_update", "lst_upd", "最后更新时间"),
    ]),
    "payment": ("pymt", "fact", "支付事实表", [
        ("payment_id", "pmt_id", "支付ID(主键)"),
        ("customer_id", "cust_id", "客户ID"),
        ("staff_id", "staf_id", "经手员工ID"),
        ("rental_id", "rnt_id", "关联租赁ID(可空)"),
        ("amount", "amt", "支付金额"),
        ("payment_date", "pmt_dt", "支付时间"),
        ("last_update", "lst_upd", "最后更新时间"),
    ]),
    "rental": ("rntl", "fact", "租赁事实表", [
        ("rental_id", "rnt_id", "租赁ID(主键)"),
        ("rental_date", "rnt_dt", "租赁时间"),
        ("inventory_id", "invt_id", "租出的库存ID"),
        ("customer_id", "cust_id", "客户ID"),
        ("return_date", "rtrn_dt", "归还时间(可空,未归则为 NULL)"),
        ("staff_id", "staf_id", "经手员工ID"),
        ("last_update", "lst_upd", "最后更新时间"),
    ]),
    "staff": ("staf", "dim", "员工维度表", [
        ("staff_id", "staf_id", "员工ID(主键)"),
        ("first_name", "frst_nm", "名"),
        ("last_name", "last_nm", "姓"),
        ("address_id", "addr_id", "住址ID"),
        ("picture", "pict", "照片(blob)"),
        ("email", "eml", "电子邮箱"),
        ("store_id", "stor_id", "所属门店ID"),
        ("active", "actv", "是否在职(1=是,0=否)"),
        ("username", "usrnm", "登录名"),
        ("password", "pwd", "密码(可空)"),
        ("last_update", "lst_upd", "最后更新时间"),
    ]),
    "store": ("stor", "dim", "门店维度表", [
        ("store_id", "stor_id", "门店ID(主键)"),
        ("manager_staff_id", "mgr_staf_id", "店长员工ID"),
        ("address_id", "addr_id", "门店地址ID"),
        ("last_update", "lst_upd", "最后更新时间"),
    ]),
    "awd": ("awd", "fact", "奖项表,颁给某演员在某影片中的表演(复合引用 flm_act)", [
        ("award_id", "awd_id", "奖项ID(主键)"),
        ("actor_id", "actr_id", "获奖演员编号"),
        ("film_id", "flm_id", "获奖影片编号"),
        ("award_name", "awd_nm", "奖项名称"),
        ("award_year", "awd_yr", "获奖年份"),
    ]),
    "card": ("card", "dim", "卡维度表,每行一张付款卡(实体卡或虚拟卡)", [
        ("card_id", "card_id", "卡ID(主键)"),
        ("cust_id", "cust_id", "持卡客户编号"),
        ("card_type", "crd_typ", "卡类型(实体卡/虚拟卡)"),
        ("card_last4", "crd_last4", "卡号后四位"),
        ("valid_to", "vld_to", "有效期"),
        ("status", "sts", "状态(active=在用/blocked=封卡/expired=过期)"),
        ("open_dt", "open_dt", "发卡日期"),
    ]),
}

# 外键(原始命名):(constraint_name, from_table, from_col, to_table, to_col)
FKS = [
    ("fk_address_city", "address", "city_id", "city", "city_id"),
    ("fk_city_country", "city", "country_id", "country", "country_id"),
    ("fk_customer_address", "customer", "address_id", "address", "address_id"),
    ("fk_customer_store", "customer", "store_id", "store", "store_id"),
    ("fk_film_language", "film", "language_id", "language", "language_id"),
    ("fk_film_language_original", "film", "original_language_id", "language", "language_id"),
    ("fk_film_actor_actor", "film_actor", "actor_id", "actor", "actor_id"),
    ("fk_film_actor_film", "film_actor", "film_id", "film", "film_id"),
    ("fk_film_category_category", "film_category", "category_id", "category", "category_id"),
    ("fk_film_category_film", "film_category", "film_id", "film", "film_id"),
    ("fk_inventory_film", "inventory", "film_id", "film", "film_id"),
    ("fk_inventory_store", "inventory", "store_id", "store", "store_id"),
    ("fk_payment_card", "payment", "customer_id", "card", "card_id"),
    ("fk_card_customer", "card", "cust_id", "customer", "customer_id"),
    ("fk_payment_rental", "payment", "rental_id", "rental", "rental_id"),
    ("fk_payment_staff", "payment", "staff_id", "staff", "staff_id"),
    ("fk_rental_customer", "rental", "customer_id", "customer", "customer_id"),
    ("fk_rental_inventory", "rental", "inventory_id", "inventory", "inventory_id"),
    ("fk_rental_staff", "rental", "staff_id", "staff", "staff_id"),
    ("fk_staff_address", "staff", "address_id", "address", "address_id"),
    ("fk_staff_store", "staff", "store_id", "store", "store_id"),
    ("fk_store_address", "store", "address_id", "address", "address_id"),
    ("fk_store_staff", "store", "manager_staff_id", "staff", "staff_id"),
    # 复合外键:awd(actor_id, film_id) 一起引用 film_actor(actor_id, film_id)
    ("fk_awd_performance", "awd", "actor_id", "film_actor", "actor_id"),
    ("fk_awd_performance", "awd", "film_id", "film_actor", "film_id"),
]


# 外键字段的「去表名化」业务描述(措施②):只讲业务角色、不点目标表名。
# 这样 M1(有字典无 ER)能做单表聚合,但无法从描述推断 JOIN 目标 → 卡在中间。
FK_ROLE_DESC = {
    ("address", "city_id"): "所在行政区编号",
    ("city", "country_id"): "隶属区域编号",
    ("customer", "store_id"): "归属网点编号",
    ("customer", "address_id"): "联系地点编号",
    ("film", "language_id"): "对白语种编号",
    ("film", "original_language_id"): "原始语种编号",
    ("film_actor", "actor_id"): "出演者编号",
    ("film_actor", "film_id"): "参演作品编号",
    ("film_category", "film_id"): "归属作品编号",
    ("film_category", "category_id"): "题材编号",
    ("inventory", "film_id"): "对应作品编号",
    ("inventory", "store_id"): "存放网点编号",
    ("payment", "customer_id"): "付款方编号",
    ("payment", "staff_id"): "经办人编号",
    ("payment", "rental_id"): "关联借出单编号",
    ("rental", "inventory_id"): "借出的实物编号",
    ("rental", "customer_id"): "租借方编号",
    ("rental", "staff_id"): "经办人编号",
    ("staff", "address_id"): "联系地点编号",
    ("staff", "store_id"): "就职网点编号",
    ("store", "manager_staff_id"): "负责人编号",
    ("store", "address_id"): "网点所在地编号",
    ("awd", "actor_id"): "获奖出演者编号",
    ("awd", "film_id"): "获奖作品编号",
    ("card", "cust_id"): "持卡客户编号",
}


def _obfuscate_fks(tables, fks, fk_desc):
    """把外键列(from 侧)改成不匹配的 `ref<N>`,并去表名化描述。

    真实数仓普遍不建外键、关联列名也对不上。保留父表 PK 列名可读,
    只把子表外键列换成无语义 `ref1/ref2/...`(按列顺序编号),这样:
      - M0 无法靠 `cust.addr_id = addr.addr_id` 这类同名推断关联;
      - 关联只能靠 sys_foreignkeys(ER)拿到。
    描述换成 fk_desc 里的业务角色措辞(不点目标表),让 M1 只知其义、不知其连。
    返回 (新 tables, {(from_table, from_col): refN})。
    """
    fk_from = {}
    for (_cname, ftab, fcol, _ttab, _tcol) in fks:
        fk_from[(ftab, fcol)] = True

    new_tables = {}
    fk_rename = {}
    for orig, (new_tbl, ttype, desc, cols) in tables.items():
        new_cols = []
        ref_n = 0
        for (oc, nc, cdesc) in cols:
            if (orig, oc) in fk_from:
                ref_n += 1
                new_nc = f"ref{ref_n}"
                fk_rename[(orig, oc)] = new_nc
                cdesc = fk_desc.get((orig, oc), cdesc)
            else:
                new_nc = nc
            new_cols.append((oc, new_nc, cdesc))
        new_tables[orig] = (new_tbl, ttype, desc, new_cols)
    return new_tables, fk_rename


# 外键列混淆成 ref<N> + 去表名化描述(措施①+②)
TABLES, FK_RENAME = _obfuscate_fks(TABLES, FKS, FK_ROLE_DESC)

TABLE_ORDER = list(TABLES.keys())


def _col_sql(orig_type, is_nullable, default, extra):
    """生成单列定义片段(不含列名)。"""
    parts = [orig_type]
    if is_nullable == "NO":
        parts.append("NOT NULL")
    if default is not None and default != "":
        if default == "CURRENT_TIMESTAMP":
            parts.append("DEFAULT CURRENT_TIMESTAMP")
        else:
            if orig_type.startswith(("enum", "set")):
                parts.append(f"DEFAULT '{default}'")
            else:
                parts.append(f"DEFAULT {default}")
    if extra == "auto_increment":
        parts.append("AUTO_INCREMENT")
    elif "on update CURRENT_TIMESTAMP" in extra:
        parts.append("ON UPDATE CURRENT_TIMESTAMP")
    return " ".join(parts)


def main():
    creds = _load_creds()
    conn = pymysql.connect(
        host=creds.get("MYSQLHOST", "localhost"),
        port=int(creds.get("MYSQLPORT", 3306)),
        user=creds["MYSQLUSER"],
        password=creds["MYSQLPASSWORD"],
        charset="utf8mb4",
    )
    cur = conn.cursor()

    # 读取原始 schema(列)
    cur.execute(
        """
        SELECT table_name, column_name, column_type, is_nullable, column_key, column_default, extra
        FROM information_schema.columns
        WHERE table_schema=%s AND table_name IN ({})
        ORDER BY table_name, ordinal_position
        """.format(",".join(["%s"] * len(TABLE_ORDER))),
        [SRC_DB] + TABLE_ORDER,
    )
    schema = {}
    for tname, cname, ctype, nullable, ckey, cdefault, extra in cur.fetchall():
        schema.setdefault(tname, []).append((cname, ctype, nullable, ckey, cdefault, extra))

    # 改名映射(用于导出)
    table_map = {orig: meta[0] for orig, meta in TABLES.items()}
    col_map = {orig: {o: n for (o, n, _) in meta[3]} for orig, meta in TABLES.items()}

    # ---- 建库(IF NOT EXISTS,幂等)+ 建表 ----
    for db in (DB_M0, DB_M1, DB_M2):
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4")
        cur.execute(f"USE `{db}`")
        for orig in TABLE_ORDER:
            cur.execute(f"DROP TABLE IF EXISTS `{TABLES[orig][0]}`")
        for t in ("sys_tables", "sys_table_fields", "sys_foreignkeys"):
            cur.execute(f"DROP TABLE IF EXISTS `{t}`")

        for orig in TABLE_ORDER:
            new_tbl, _, _, cols = TABLES[orig]
            new_cols = [n for (_, n, _) in cols]
            # 列定义(按原始 schema 顺序 + 我们的描述列顺序)
            col_defs = []
            pk_cols = []
            for (oc, nc, _) in cols:
                if orig == "awd":
                    ctype, nullable, ckey, cdefault, extra = _AWD_COLUMNS[oc]
                elif orig == "card":
                    ctype, nullable, ckey, cdefault, extra = _CARD_COLUMNS[oc]
                else:
                    _, ctype, nullable, ckey, cdefault, extra = next(
                        x for x in schema[orig] if x[0] == oc
                    )
                col_defs.append(f"`{nc}` {_col_sql(ctype, nullable, cdefault, extra)}")
                if ckey == "PRI":
                    pk_cols.append(nc)
            pk_sql = f"PRIMARY KEY ({', '.join('`'+c+'`' for c in pk_cols)})" if pk_cols else ""
            create = (
                f"CREATE TABLE `{new_tbl}` (\n  "
                + ",\n  ".join(col_defs)
                + (",\n  " + pk_sql if pk_sql else "")
                + "\n) ENGINE=InnoDB"
            )
            cur.execute(create)
            if orig == "awd":
                # 合成获奖数据:前 AWARD_ACTORS 个 distinct 演员,演员 i 获 (AWARD_ACTORS+1-i) 个奖
                col_by_orig = {oc: nc for (oc, nc, _) in cols}
                cur.execute(
                    f"SELECT DISTINCT actor_id FROM `{SRC_DB}`.film_actor ORDER BY actor_id LIMIT {AWARD_ACTORS}"
                )
                actors = [r[0] for r in cur.fetchall()]
                award_rows = []
                award_id = 0
                for i, aid in enumerate(actors, 1):
                    k = AWARD_ACTORS + 1 - i
                    cur.execute(
                        f"SELECT film_id FROM `{SRC_DB}`.film_actor WHERE actor_id={aid} ORDER BY film_id LIMIT {k}"
                    )
                    for fid in [r[0] for r in cur.fetchall()]:
                        award_id += 1
                        name = AWARD_NAMES[(award_id - 1) % len(AWARD_NAMES)]
                        year = 2005 + ((award_id - 1) % 2)
                        award_rows.append((award_id, aid, fid, name, year))
                cur.executemany(
                    f"INSERT INTO `{new_tbl}` (`{col_by_orig['award_id']}`, `{col_by_orig['actor_id']}`, `{col_by_orig['film_id']}`, `{col_by_orig['award_name']}`, `{col_by_orig['award_year']}`) VALUES (%s, %s, %s, %s, %s)",
                    award_rows,
                )
            elif orig == "card":
                # 合成付款卡数据:每个客户一张主卡(实体卡/active,2005-07-01 起用);cid % 3 == 0 的客户曾用过一张虚拟卡(短有效期,2005-06-30 到期封卡/过期后改用新卡)
                col_by_orig = {oc: nc for (oc, nc, _) in cols}
                cur.execute(f"SELECT customer_id FROM `{SRC_DB}`.customer ORDER BY customer_id")
                cust_ids = [r[0] for r in cur.fetchall()]
                card_rows = []
                for cid in cust_ids:
                    card_rows.append((1000 + cid, cid, "实体卡", str(cid).zfill(4), "2010-12-31", "active", "2005-07-01"))
                for cid in cust_ids:
                    if cid % 3 == 0:
                        sts = "expired" if (cid // 3) % 2 == 0 else "blocked"
                        card_rows.append((3000 + cid, cid, "虚拟卡", str(3000 + cid)[-4:], "2005-06-30", sts, "2005-01-01"))
                cur.executemany(
                    f"INSERT INTO `{new_tbl}` (`{col_by_orig['card_id']}`, `{col_by_orig['cust_id']}`, `{col_by_orig['card_type']}`, `{col_by_orig['card_last4']}`, `{col_by_orig['valid_to']}`, `{col_by_orig['status']}`, `{col_by_orig['open_dt']}`) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    card_rows,
                )
            elif orig == "payment":
                # payment.customer_id 重接为 card.card_id:换卡客户(cid%3==0)在 2005-06-30 前用旧虚拟卡(3000+cid),之后用新卡(1000+cid);其余客户用新卡
                dst_cols = ", ".join(f"`{nc}`" for (_, nc, _) in cols)
                src_parts = [
                    "CASE WHEN customer_id % 3 = 0 AND payment_date <= '2005-06-30' THEN 3000 + customer_id ELSE 1000 + customer_id END"
                    if oc == "customer_id" else f"`{oc}`"
                    for (oc, _nc, _) in cols
                ]
                cur.execute(
                    f"INSERT INTO `{new_tbl}` ({dst_cols}) SELECT {', '.join(src_parts)} FROM `{SRC_DB}`.`payment`"
                )
            elif orig == "film_text":
                # doc(原 film_text 冗余表):命名去关联化 + 子集(G/PG/PG-13)+ 55 部片名故意写旧(制造「ER 之外的隐藏关系 + 数据不一致」)
                dst_cols = ", ".join(f"`{nc}`" for (_, nc, _) in cols)
                cur.execute(
                    f"INSERT INTO `{new_tbl}` ({dst_cols}) "
                    f"SELECT ft.`film_id`, "
                    f"  CASE WHEN ft.`film_id` % 12 = 0 THEN CONCAT(ft.`title`, ' (旧版)') ELSE ft.`title` END, "
                    f"  ft.`description` "
                    f"FROM `{SRC_DB}`.`film_text` ft JOIN `{SRC_DB}`.`film` f ON ft.`film_id` = f.`film_id` "
                    f"WHERE f.`rating` IN ('G','PG','PG-13')"
                )
            else:
                # 拷贝数据
                src_cols = ", ".join(f"`{oc}`" for (oc, _, _) in cols)
                dst_cols = ", ".join(f"`{nc}`" for (_, nc, _) in cols)
                cur.execute(
                    f"INSERT INTO `{new_tbl}` ({dst_cols}) SELECT {src_cols} FROM `{SRC_DB}`.`{orig}`"
                )

    # ---- sys 表(M1 = 字典两表;M2 = 字典两表 + ER) ----
    _SYS_TABLES_DDL = """
        CREATE TABLE `sys_tables` (
          `table_name` varchar(64) NOT NULL,
          `table_desc` varchar(512) NOT NULL,
          `table_type` varchar(16) NOT NULL COMMENT 'fact | dim | junction',
          PRIMARY KEY (`table_name`)
        ) ENGINE=InnoDB
        """
    _SYS_FIELDS_DDL = """
        CREATE TABLE `sys_table_fields` (
          `table_name` varchar(64) NOT NULL,
          `field_name` varchar(64) NOT NULL,
          `field_desc` varchar(512) NOT NULL,
          PRIMARY KEY (`table_name`, `field_name`)
        ) ENGINE=InnoDB
        """
    _SYS_FK_DDL = """
        CREATE TABLE `sys_foreignkeys` (
          `constraint_name` varchar(64) NOT NULL,
          `from_table` varchar(64) NOT NULL,
          `from_column` varchar(64) NOT NULL,
          `to_table` varchar(64) NOT NULL,
          `to_column` varchar(64) NOT NULL,
          `column_seq` int NOT NULL DEFAULT 1 COMMENT '复合外键中的列序号(1-based)',
          `column_count` int NOT NULL DEFAULT 1 COMMENT '外键总列数(1=单列,N=复合)',
          `source` varchar(16) NOT NULL DEFAULT 'manual' COMMENT 'manual | inferred',
          `confidence` decimal(3,2) NOT NULL DEFAULT 1.00,
          PRIMARY KEY (`constraint_name`, `from_column`)
        ) ENGINE=InnoDB
        """

    for db, with_er in ((DB_M1, False), (DB_M2, True)):
        cur.execute(f"USE `{db}`")
        cur.execute(_SYS_TABLES_DDL)
        cur.execute(_SYS_FIELDS_DDL)
        if with_er:
            cur.execute(_SYS_FK_DDL)

        # sys_tables
        for orig in TABLE_ORDER:
            new_tbl, ttype, desc, _ = TABLES[orig]
            cur.execute(
                "INSERT INTO `sys_tables` VALUES (%s, %s, %s)", (new_tbl, desc, ttype)
            )
        # sys_table_fields
        for orig in TABLE_ORDER:
            new_tbl, _, _, cols = TABLES[orig]
            for (_, nc, fdesc) in cols:
                cur.execute(
                    "INSERT INTO `sys_table_fields` VALUES (%s, %s, %s)",
                    (new_tbl, nc, fdesc),
                )
        # sys_foreignkeys(仅 M2)
        if with_er:
            # 按 constraint_name 分组,算复合外键的 column_seq / column_count
            fk_groups = {}
            for (cname, ftab, fcol, ttab, tcol) in FKS:
                fk_groups.setdefault(cname, []).append((ftab, fcol, ttab, tcol))
            for cname, cols in fk_groups.items():
                n = len(cols)
                for seq, (ftab, fcol, ttab, tcol) in enumerate(cols, 1):
                    cur.execute(
                        "INSERT INTO `sys_foreignkeys` VALUES (%s, %s, %s, %s, %s, %s, %s, 'manual', 1.00)",
                        (cname, table_map[ftab], col_map[ftab][fcol], table_map[ttab], col_map[ttab][tcol], seq, n),
                    )

    conn.commit()

    # 导出改名映射
    os.makedirs(os.path.dirname(OUT_MAP), exist_ok=True)
    with open(OUT_MAP, "w", encoding="utf-8") as f:
        json.dump(
            {
                "source_db": SRC_DB,
                "db_m0": DB_M0,
                "db_m1": DB_M1,
                "db_m2": DB_M2,
                "tables": table_map,
                "columns": col_map,
                "foreign_keys": [
                    {
                        "constraint": cname,
                        "from_table": table_map[ftab],
                        "from_column": col_map[ftab][fcol],
                        "to_table": table_map[ttab],
                        "to_column": col_map[ttab][tcol],
                    }
                    for (cname, ftab, fcol, ttab, tcol) in FKS
                ],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    # 统计
    stats = {}
    for db in (DB_M0, DB_M1, DB_M2):
        cur.execute(
            "SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema=%s ORDER BY table_name",
            (db,),
        )
        stats[db] = {t: r for t, r in cur.fetchall()}
    cur.close()
    conn.close()

    print("改名映射已导出:", OUT_MAP)
    for db in (DB_M0, DB_M1, DB_M2):
        print(f"\n== {db} ==")
        for t, r in stats[db].items():
            print(f"  {t:22s} {r} 行")


if __name__ == "__main__":
    main()
