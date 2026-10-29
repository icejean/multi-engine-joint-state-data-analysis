#!/usr/bin/env python3
"""从 BIRD train.json 里筛选有区分度的题目集(优先多表 join)。

用法:
    python3 select_questions.py --train-json <path> --db-id works_cycles --target 100 --out <path>

策略:
    1. 全部 ≥2 JOIN 的多表题(ER 图区分度的核心)。
    2. 从 1-JOIN 题里按特征丰富度(子查询/聚合/CASE/HAVING)补足到 target。
    3. 0-JOIN 单表题不入选(对 ER 图无区分度)。
"""

import argparse, json, re
from collections import Counter

# 表 -> 业务域(粗略)
DOMAIN = {
    'Person': 'HR', 'Employee': 'HR', 'Department': 'HR', 'Shift': 'HR',
    'EmployeePayHistory': 'HR', 'EmployeeDepartmentHistory': 'HR',
    'JobCandidate': 'HR', 'Document': 'HR', 'EmailAddress': 'HR', 'Password': 'HR',
    'PhoneNumberType': 'HR',
    'Product': 'Product', 'ProductCategory': 'Product', 'ProductSubcategory': 'Product',
    'ProductModel': 'Product', 'ProductCostHistory': 'Product', 'ProductListPriceHistory': 'Product',
    'ProductInventory': 'Product', 'ProductReview': 'Product', 'ProductPhoto': 'Product',
    'ProductDocument': 'Product', 'ProductProductPhoto': 'Product',
    'ProductModelProductDescriptionCulture': 'Product', 'BillOfMaterials': 'Product',
    'UnitMeasure': 'Product', 'ProductDescription': 'Product',
    'WorkOrder': 'Product', 'WorkOrderRouting': 'Product', 'TransactionHistory': 'Product',
    'TransactionHistoryArchive': 'Product', 'ScrapReason': 'Product', 'Location': 'Product',
    'Culture': 'Product', 'SpecialOffer': 'Sales', 'SpecialOfferProduct': 'Sales',
    'Vendor': 'Purchasing', 'ProductVendor': 'Purchasing', 'PurchaseOrderHeader': 'Purchasing',
    'PurchaseOrderDetail': 'Purchasing', 'ShipMethod': 'Purchasing',
    'SalesOrderHeader': 'Sales', 'SalesOrderDetail': 'Sales', 'Customer': 'Sales',
    'PersonCreditCard': 'Sales', 'CreditCard': 'Sales', 'SalesPerson': 'Sales',
    'SalesTerritory': 'Sales', 'SalesReason': 'Sales', 'SalesOrderHeaderSalesReason': 'Sales',
    'Currency': 'Sales', 'CurrencyRate': 'Sales', 'CountryRegionCurrency': 'Sales',
    'SalesTaxRate': 'Sales', 'ShoppingCartItem': 'Sales', 'SalesTerritoryHistory': 'Sales',
    'SalesPersonQuotaHistory': 'Sales', 'Store': 'Sales',
    'Address': 'Geography', 'AddressType': 'Geography', 'StateProvince': 'Geography',
    'CountryRegion': 'Geography', 'BusinessEntity': 'Geography', 'BusinessEntityAddress': 'Geography',
    'BusinessEntityContact': 'Geography', 'ContactType': 'Geography',
}


def features(sql):
    s = sql.upper()
    f, nj = [], len(re.findall(r'\bJOIN\b', s))
    if nj:
        f.append(f"JOIN×{nj}")
    if re.search(r'\bGROUP\s+BY\b', s):
        f.append("GROUP_BY")
    if re.search(r'\bHAVING\b', s):
        f.append("HAVING")
    if re.search(r'\bCASE\b', s):
        f.append("CASE")
    if re.search(r'\(\s*SELECT\b', s):
        f.append("SUBQUERY")
    if re.search(r'\bEXISTS\b', s):
        f.append("EXISTS")
    return f, nj


def domain(sql):
    tbls = set(re.findall(r'(?:FROM|JOIN)\s+([A-Za-z_]+)', sql, re.I))
    ds = Counter(DOMAIN.get(t, 'Other') for t in tbls)
    return ds.most_common(1)[0][0] if ds else 'Other'


def enrich(rows):
    out = []
    for d in rows:
        f, nj = features(d['SQL'])
        out.append({**d, 'join_count': nj, 'features': f, 'domain': domain(d['SQL'])})
    return out


def score(e):
    f = e['features']
    return (2 * ('SUBQUERY' in f or 'EXISTS' in f)) + ('GROUP_BY' in f) + ('CASE' in f) + ('HAVING' in f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--train-json', required=True)
    ap.add_argument('--db-id', default='works_cycles')
    ap.add_argument('--target', type=int, default=100)
    ap.add_argument('--out', default='question_set.json')
    args = ap.parse_args()

    data = json.load(open(args.train_json))
    wc = enrich([d for d in data if d['db_id'] == args.db_id])
    print(f"{args.db_id} 总题数: {len(wc)}")

    multi = [e for e in wc if e['join_count'] >= 2]
    one_join = sorted([e for e in wc if e['join_count'] == 1],
                      key=lambda e: (-score(e), e['question']))
    need = args.target - len(multi)
    if need < 0:
        multi.sort(key=lambda e: (-e['join_count'], e['question']))
        selected = multi[:args.target]
        n_multi_kept, n_one_added = args.target, 0
    else:
        selected = multi + one_join[:need]
        n_multi_kept, n_one_added = len(multi), max(0, need)

    selected.sort(key=lambda e: (e['join_count'], e['question']))

    out = {
        "name": f"{args.db_id}_question_set_{len(selected)}",
        "description": f"三梯度测试用 {len(selected)} 道有区分度的题(优先多表 join)",
        "selection": {"multi_join_kept": n_multi_kept, "one_join_added": n_one_added},
        "questions": selected,
    }
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"已选 {len(selected)} 题 -> {args.out}")

    print("\n=== JOIN 分布 ===")
    for k, v in sorted(Counter(e['join_count'] for e in selected).items()):
        print(f"  {k} JOIN: {v}")
    print("\n=== 特征分布 ===")
    fc = Counter(x for e in selected for x in e['features'])
    for k, v in fc.most_common():
        print(f"  {k}: {v}")
    print("\n=== 领域分布 ===")
    for k, v in Counter(e['domain'] for e in selected).most_common():
        print(f"  {k}: {v}")
    print("\n=== 样例(每 JOIN 档 1 题) ===")
    seen = set()
    for e in selected:
        if e['join_count'] not in seen:
            seen.add(e['join_count'])
            print(f"  [{e['join_count']} JOIN | {e['domain']}] {e['question'][:70]}")


if __name__ == '__main__':
    main()
