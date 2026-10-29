#!/usr/bin/env python3
"""生成 works_cycles 的混淆映射(表名/列名缩写 + FK 列改 ref1/ref2)。

用法:
    python3 generate_obfuscation_map.py --sqlite works_cycles.sqlite --out obfuscation_map.json

规则(对齐 Sakila 三梯度库):
    - 表名: 手动缩写映射(65 表)。
    - 非 FK 列: CamelCase 拆词 -> 去元音 -> 每词截 4 字符。
    - FK 列: 按声明顺序改名为 ref1/ref2/... (失去语义提示)。
    - 输出可逆映射: 原名 <-> 缩写名 + 主键 + 外键。
"""

import argparse, json, re, sqlite3

# 65 张表的手动缩写(去元音风格, 与 Sakila actr/addr/cust 一致)
TABLE_ABBREV = {
    'Address': 'addr', 'AddressType': 'addr_typ', 'BillOfMaterials': 'bom',
    'BusinessEntity': 'biz_ent', 'BusinessEntityAddress': 'biz_addr', 'BusinessEntityContact': 'biz_cnt',
    'ContactType': 'cnt_typ', 'CountryRegion': 'cnty', 'CountryRegionCurrency': 'cnty_cur',
    'CreditCard': 'crd', 'Culture': 'cult', 'Currency': 'cur', 'CurrencyRate': 'cur_rate',
    'Customer': 'cust', 'Department': 'dept', 'Document': 'doc', 'EmailAddress': 'eml',
    'Employee': 'emp', 'EmployeeDepartmentHistory': 'emp_dept_hist', 'EmployeePayHistory': 'emp_pay_hist',
    'JobCandidate': 'job_cand', 'Location': 'loc', 'Password': 'pwd', 'Person': 'prsn',
    'PersonCreditCard': 'prsn_crd', 'PhoneNumberType': 'phn_typ', 'Product': 'prod',
    'ProductCategory': 'prod_cat', 'ProductCostHistory': 'prod_cst_hist', 'ProductDescription': 'prod_dsc',
    'ProductDocument': 'prod_doc', 'ProductInventory': 'prod_inv', 'ProductListPriceHistory': 'prod_lst_hist',
    'ProductModel': 'prod_mdl', 'ProductModelProductDescriptionCulture': 'pmdc', 'ProductPhoto': 'prod_ph',
    'ProductProductPhoto': 'ppp', 'ProductReview': 'prod_rvw', 'ProductSubcategory': 'prod_sub',
    'ProductVendor': 'prod_vnd', 'PurchaseOrderDetail': 'po_dtl', 'PurchaseOrderHeader': 'po_hdr',
    'SalesOrderDetail': 'so_dtl', 'SalesOrderHeader': 'so_hdr', 'SalesOrderHeaderSalesReason': 'so_rsn',
    'SalesPerson': 'sls_prsn', 'SalesPersonQuotaHistory': 'sp_q_hist', 'SalesReason': 'sls_rsn',
    'SalesTaxRate': 'sls_tax', 'SalesTerritory': 'sls_terr', 'SalesTerritoryHistory': 'sls_terr_hist',
    'ScrapReason': 'scrp', 'Shift': 'shft', 'ShipMethod': 'shp_mth', 'ShoppingCartItem': 'cart_itm',
    'SpecialOffer': 'spcl_offr', 'SpecialOfferProduct': 'spcl_prod', 'StateProvince': 'st_prv',
    'Store': 'stor', 'TransactionHistory': 'txn_hist', 'TransactionHistoryArchive': 'txn_hist_a',
    'UnitMeasure': 'unit_msr', 'Vendor': 'vnd', 'WorkOrder': 'wo', 'WorkOrderRouting': 'wo_rtg',
}

VOWELS = set('aeiou')

# 已知的 BIRD 导出 bug: SalesOrderHeader.ShipMethodID 被错声明为指向 Address
FK_CORRECTIONS = {
    ("SalesOrderHeader", "ShipMethodID"): "ShipMethod",
}


def split_camel(s):
    s = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', s)
    s = re.sub(r'(?<=[A-Z])(?=[A-Z][a-z])', ' ', s)
    return s.split()


def abbrev_word(w):
    wl = w.lower()
    core = wl[0] + ''.join(c for c in wl[1:] if c not in VOWELS)
    core = core[:4]
    return core if len(core) >= 2 else wl[:4]


def abbrev_col(name):
    return '_'.join(abbrev_word(w) for w in split_camel(name))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sqlite', default='works_cycles.sqlite')
    ap.add_argument('--out', default='obfuscation_map.json')
    args = ap.parse_args()

    con = sqlite3.connect(args.sqlite)
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]

    # 校验表缩写唯一
    assert len(set(TABLE_ABBREV.values())) == len(TABLE_ABBREV), "表缩写有重复!"
    missing = [t for t in tables if t not in TABLE_ABBREV]
    assert not missing, f"缺表缩写: {missing}"

    mapping = {}
    for t in tables:
        cols = {r[1]: r for r in con.execute(f'PRAGMA table_info("{t}")')}  # name -> (cid,name,type,nn,dv,pk)
        # FK 列(按声明顺序去重)
        fk_from = []
        for fk in con.execute(f'PRAGMA foreign_key_list("{t}")'):
            if fk[3] not in fk_from:
                fk_from.append(fk[3])
        # 列映射: FK 列 -> ref1/ref2, 其余缩写
        col_map = {}
        used = {}
        for cname in cols:
            if cname in fk_from:
                obf = f"ref{fk_from.index(cname) + 1}"
            else:
                obf = abbrev_col(cname)
                # 碰撞处理
                if obf in used:
                    used[obf] += 1
                    obf = f"{obf}{used[obf]}"
                else:
                    used[obf] = 1
            col_map[cname] = obf

        # 主键(缩写后)
        pk = sorted((cols[c][5], col_map[c]) for c in cols if cols[c][5] > 0)
        pk_obf = [n for _, n in pk]

        # 外键(缩写后 from/to)
        fks = []
        for fk in con.execute(f'PRAGMA foreign_key_list("{t}")'):
            fk_id, seq, ref_t, from_c, to_c = fk[0], fk[1], fk[2], fk[3], fk[4]
            corr = FK_CORRECTIONS.get((t, from_c))
            if corr:
                ref_t, to_c = corr, ''
            if not to_c:
                # 目标列空 -> 目标表主键
                rp = con.execute(f'PRAGMA table_info("{ref_t}")').fetchall()
                to_c = sorted([(r[5], r[1]) for r in rp if r[5] > 0])[0][1]
            fks.append({
                "constraint": f"fk_{TABLE_ABBREV[t]}_{TABLE_ABBREV[ref_t]}",
                "from_col": col_map[from_c],
                "to_table": TABLE_ABBREV[ref_t],
                "to_col": None,  # 目标列缩写需第二遍解析
                "_ref_t": ref_t, "_ref_c": to_c,
            })

        mapping[t] = {
            "abbrev": TABLE_ABBREV[t],
            "columns": col_map,          # 原名 -> 缩写名
            "pk": pk_obf,                # 缩写后的主键
            "fks": fks,                  # 外键(from_col 已缩写, to 待解析)
        }

    # 第二遍: 解析 FK 目标列缩写
    for t, m in mapping.items():
        for fk in m['fks']:
            to_t = fk['_ref_t']
            to_c = fk['_ref_c']
            fk['to_col'] = mapping[to_t]['columns'][to_c]
            del fk['_ref_t']; del fk['_ref_c']

    con.close()

    # 校验: 列缩写全局唯一(表内)
    for t, m in mapping.items():
        vals = list(m['columns'].values())
        assert len(set(vals)) == len(vals), f"{t} 列缩写重复: {vals}"

    json.dump(mapping, open(args.out, 'w'), ensure_ascii=False, indent=2)
    n_fk = sum(len(m['fks']) for m in mapping.values())
    print(f"表 {len(mapping)} 张, FK {n_fk} 条 -> {args.out}")
    # 抽样展示
    for t in ['Customer', 'SalesOrderHeader', 'BillOfMaterials']:
        m = mapping[t]
        print(f"\n[{t}] -> {m['abbrev']} pk={m['pk']}")
        print("  列映射:", {k: v for k, v in list(m['columns'].items())[:6]}, "...")
        print("  FK:", [(f['from_col'], f['to_table'], f['to_col']) for f in m['fks']])


if __name__ == '__main__':
    main()
