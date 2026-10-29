#!/usr/bin/env python3
"""生成 works_cycles 的中文描述(表描述+类型分类 + 字段中文 gloss)。

用法:
    python3 generate_descriptions.py --map obfuscation_map.json \
        --desc-dir database_description --out descriptions.json

输出 descriptions.json:
    { "<原名表>": {"type": "fact|dim|junction", "desc": "中文", "fields": {"<原名列>": "中文gloss"}} }
"""

import argparse, csv, io, json, os, re

# 表 -> (类型, 中文描述)
TABLE_META = {
    # 销售
    'SalesOrderHeader': ('fact', '销售订单头表,每笔订单一行(客户/日期/金额/收货地址)'),
    'SalesOrderDetail': ('fact', '销售订单明细表,每个订单行一个产品及其数量/价格'),
    'SalesOrderHeaderSalesReason': ('junction', '销售订单-销售原因关联表(多对多)'),
    'SalesPerson': ('dim', '销售员维度表'),
    'SalesTerritory': ('dim', '销售区域维度表'),
    'SalesTerritoryHistory': ('fact', '销售员-区域任职历史表'),
    'SalesPersonQuotaHistory': ('fact', '销售员配额历史表'),
    'SalesReason': ('dim', '销售原因维度表'),
    'SalesTaxRate': ('fact', '销售税率表'),
    'SpecialOffer': ('dim', '促销优惠维度表'),
    'SpecialOfferProduct': ('junction', '促销-产品关联表(多对多)'),
    'ShoppingCartItem': ('junction', '购物车条目表'),
    'Customer': ('dim', '客户维度表(个人或门店)'),
    'Store': ('dim', '门店维度表(公司客户)'),
    'PersonCreditCard': ('junction', '个人-信用卡关联表(多对多)'),
    'CreditCard': ('dim', '信用卡维度表'),
    'Currency': ('dim', '货币维度表'),
    'CurrencyRate': ('fact', '货币汇率表'),
    'CountryRegionCurrency': ('junction', '国家-货币关联表'),
    # 人/HR
    'Person': ('dim', '人员维度表,含姓名/类型'),
    'Employee': ('dim', '员工维度表(带职位/工号)'),
    'EmployeeDepartmentHistory': ('fact', '员工-部门任职历史表(时间区间)'),
    'EmployeePayHistory': ('fact', '员工薪资历史表'),
    'Department': ('dim', '部门维度表'),
    'Shift': ('dim', '班次维度表'),
    'JobCandidate': ('dim', '求职者维度表'),
    'EmailAddress': ('dim', '邮箱地址表'),
    'Password': ('dim', '登录密码表'),
    'PhoneNumberType': ('dim', '电话类型维度表'),
    'BusinessEntity': ('dim', '业务实体主表(个人/门店的父类型)'),
    'BusinessEntityAddress': ('junction', '实体-地址关联表(多对多)'),
    'BusinessEntityContact': ('junction', '实体-联系人关联表(多对多)'),
    'ContactType': ('dim', '联系类型维度表'),
    'AddressType': ('dim', '地址类型维度表'),
    # 产品
    'Product': ('dim', '产品维度表,含名称/价格/成本'),
    'ProductCategory': ('dim', '产品大类维度表'),
    'ProductSubcategory': ('dim', '产品子类维度表'),
    'ProductModel': ('dim', '产品型号维度表'),
    'ProductCostHistory': ('fact', '产品成本历史表'),
    'ProductListPriceHistory': ('fact', '产品标价历史表'),
    'ProductInventory': ('fact', '产品库存表'),
    'ProductReview': ('fact', '产品评论表'),
    'ProductPhoto': ('dim', '产品照片表'),
    'ProductDocument': ('junction', '产品-文档关联表(多对多)'),
    'ProductProductPhoto': ('junction', '产品-照片关联表(多对多)'),
    'ProductModelProductDescriptionCulture': ('junction', '型号-描述-文化关联表'),
    'ProductDescription': ('dim', '产品描述维度表'),
    'BillOfMaterials': ('fact', '物料清单表,产品装配关系(自引用/递归)'),
    'UnitMeasure': ('dim', '计量单位维度表'),
    # 采购
    'Vendor': ('dim', '供应商维度表'),
    'ProductVendor': ('junction', '产品-供应商关联表(多对多)'),
    'PurchaseOrderHeader': ('fact', '采购订单头表'),
    'PurchaseOrderDetail': ('fact', '采购订单明细表'),
    'ShipMethod': ('dim', '运输方式维度表'),
    # 生产
    'WorkOrder': ('fact', '生产工单表'),
    'WorkOrderRouting': ('fact', '生产工序路由表'),
    'TransactionHistory': ('fact', '库存事务历史表'),
    'TransactionHistoryArchive': ('fact', '库存事务历史归档表'),
    'ScrapReason': ('dim', '报废原因维度表'),
    'Location': ('dim', '生产位置维度表'),
    'Culture': ('dim', '文化/语言维度表'),
    # 地理
    'Address': ('dim', '地址维度表'),
    'StateProvince': ('dim', '州/省维度表'),
    'CountryRegion': ('dim', '国家/地区维度表'),
    # 其他
    'Document': ('dim', '文档表'),
}

# 字段名 -> 中文(精确覆盖, 优先于词表)
FIELD_OVERRIDE = {
    'rowguid': '行GUID', 'ModifiedDate': '最后修改时间', 'Name': '名称',
    'Status': '状态', 'AccountNumber': '账户编号', 'Comment': '备注',
    'SubTotal': '小计金额', 'TaxAmt': '税额', 'Freight': '运费', 'TotalDue': '应付总额',
    'OrderQty': '订购数量', 'UnitPrice': '单价', 'UnitPriceDiscount': '单价折扣', 'LineTotal': '行总额',
    'OrderDate': '下单日期', 'DueDate': '到期日期', 'ShipDate': '发货日期',
    'ListPrice': '标价', 'StandardCost': '标准成本', 'Weight': '重量', 'Color': '颜色', 'Size': '尺寸',
    'FirstName': '名', 'LastName': '姓', 'MiddleName': '中间名', 'Suffix': '后缀',
    'Class': '等级', 'Style': '款式', 'ProductLine': '产品线', 'ProductNumber': '产品编号',
    'Demographics': '人口统计信息', 'AdditionalContactInfo': '补充联系信息', 'EmailPromotion': '邮件促销标记',
    'BillOfMaterialsID': '物料清单编号', 'BOMLevel': '物料层级', 'PerAssemblyQty': '每装配数量',
}

# ref 列(外键列)的中文 gloss 覆盖: 原列名小写 -> 语义描述(区分同表多外键的角色)
REF_OVERRIDE = {
    'productassemblyid': '装配产品编号', 'componentid': '组件编号',
    'billtoaddressid': '账单地址编号', 'shiptoaddressid': '收货地址编号',
    'fromcurrencycode': '源货币代码', 'tocurrencycode': '目标货币代码',
    'personid': '个人编号', 'storeid': '门店编号', 'salespersonid': '销售员编号',
    'weightunitmeasurecode': '重量单位代码', 'sizeunitmeasurecode': '尺寸单位代码',
    # SalesOrderDetail 的复合外键 ProductID+SpecialOfferID 都指向 junction 表 SpecialOfferProduct，
    # 若走「FK 目标表短名」回退会两个都写成「促销-产品编号」，失去区分度 → 显式覆盖角色语义。
    'productid': '产品编号', 'specialofferid': '促销编号',
}

# (原名表, 原名列) -> 中文 gloss(表感知覆盖:修正词表误译/漏译,含 column_description 语义)
# 词表逐词拼出来的 gloss 有两类缺陷:① camelCase 未覆盖 → 漏出英文原词;② 多义词误译
# (如 rate→汇率、last→姓)。此表对全部缺陷字段做显式覆盖,优先于 FIELD_OVERRIDE / WORD_GLOSS。
TABLE_FIELD_OVERRIDE = {
    ('Address', 'SpatialLocation'): '空间位置',
    ('BillOfMaterials', 'BOMLevel'): '物料层级(全局层级号,0=顶层成品;求某产品的最深装配层级时,用递归CTE里 level+1 累计,勿用本列)',
    ('CountryRegionCurrency', 'CurrencyCode'): '货币代码',
    ('Currency', 'CurrencyCode'): '货币代码(ISO标准)',
    ('CurrencyRate', 'CurrencyRateDate'): '汇率日期',
    ('CurrencyRate', 'AverageRate'): '日均汇率',
    ('CurrencyRate', 'EndOfDayRate'): '收盘汇率',
    ('Document', 'DocumentNode'): '文档层级节点',
    ('Document', 'DocumentLevel'): '文档层级深度',
    ('Document', 'FolderFlag'): '是否文件夹',
    ('Document', 'FileName'): '文件名',
    ('Document', 'FileExtension'): '文件扩展名',
    ('Document', 'ChangeNumber'): '变更编号',
    ('Document', 'DocumentSummary'): '文档摘要',
    ('Document', 'Document'): '文档内容',
    ('Employee', 'NationalIDNumber'): '身份证号',
    ('Employee', 'LoginID'): '登录账号',
    ('Employee', 'OrganizationNode'): '组织层级节点(公司层级位置)',
    ('Employee', 'OrganizationLevel'): '组织层级深度',
    ('Employee', 'BirthDate'): '出生日期',
    ('Employee', 'MaritalStatus'): '婚姻状况',
    ('Employee', 'Gender'): '性别',
    ('Employee', 'HireDate'): '入职日期',
    ('Employee', 'SalariedFlag'): '是否领薪',
    ('Employee', 'VacationHours'): '可用年假小时数',
    ('Employee', 'SickLeaveHours'): '可用病假小时数',
    ('Employee', 'CurrentFlag'): '当前在职标志',
    ('EmployeePayHistory', 'RateChangeDate'): '调薪日期',
    ('EmployeePayHistory', 'PayFrequency'): '发薪频率',
    ('EmployeePayHistory', 'Rate'): '时薪(小时工资率)',
    ('JobCandidate', 'Resume'): '简历',
    ('Location', 'Availability'): '可用工时(小时)',
    ('Location', 'CostRate'): '小时成本率',
    ('Password', 'PasswordHash'): '密码哈希',
    ('Password', 'PasswordSalt'): '密码盐',
    ('Product', 'MakeFlag'): '是否自制',
    ('Product', 'FinishedGoodsFlag'): '是否成品(可售)',
    ('Product', 'SafetyStockLevel'): '最低库存量(安全库存)',
    ('Product', 'ReorderPoint'): '再订货点(触发补货)',
    ('Product', 'Class'): '质量等级',
    ('Product', 'Style'): '款式',
    ('Product', 'ProductLine'): '产品线',
    ('ProductInventory', 'Shelf'): '货架',
    ('ProductInventory', 'Bin'): '货位',
    ('ProductModel', 'CatalogDescription'): '目录描述',
    ('ProductModel', 'Instructions'): '使用说明',
    ('ProductPhoto', 'ProductPhotoID'): '产品照片编号',
    ('ProductPhoto', 'ThumbNailPhoto'): '缩略图',
    ('ProductPhoto', 'ThumbnailPhotoFileName'): '缩略图文件名',
    ('ProductPhoto', 'LargePhoto'): '大图',
    ('ProductPhoto', 'LargePhotoFileName'): '大图文件名',
    ('ProductProductPhoto', 'Primary'): '是否主图',
    ('ProductReview', 'ProductReviewID'): '产品评论编号',
    ('ProductReview', 'ReviewerName'): '评论者姓名',
    ('ProductReview', 'ReviewDate'): '评论日期',
    ('ProductReview', 'Rating'): '评分',
    ('ProductVendor', 'AverageLeadTime'): '平均交货期',
    ('ProductVendor', 'LastReceiptCost'): '上次收货成本',
    ('ProductVendor', 'LastReceiptDate'): '上次收货日期',
    ('ProductVendor', 'MinOrderQty'): '最小订购数量',
    ('ProductVendor', 'MaxOrderQty'): '最大订购数量',
    ('ProductVendor', 'OnOrderQty'): '在途订购数量',
    ('PurchaseOrderDetail', 'ReceivedQty'): '已收数量',
    ('PurchaseOrderDetail', 'RejectedQty'): '拒收数量',
    ('PurchaseOrderDetail', 'StockedQty'): '入库数量',
    ('PurchaseOrderHeader', 'EmployeeID'): '创建订单员工编号',
    ('SalesOrderDetail', 'CarrierTrackingNumber'): '承运人追踪号',
    ('SalesOrderHeader', 'CreditCardApprovalCode'): '信用卡授权码',
    ('SalesPerson', 'CommissionPct'): '佣金比例',
    ('SalesReason', 'ReasonType'): '原因类型',
    ('SalesTaxRate', 'SalesTaxRateID'): '销售税率编号',
    ('SalesTaxRate', 'TaxRate'): '税率',
    ('SalesTerritory', 'Group'): '地理分组',
    ('SalesTerritory', 'CostYTD'): '年初至今成本',
    ('SalesTerritory', 'CostLastYear'): '去年成本',
    ('ShipMethod', 'ShipBase'): '基础运费',
    ('ShipMethod', 'ShipRate'): '每磅运费',
    ('SpecialOffer', 'DiscountPct'): '折扣比例',
    ('SpecialOffer', 'MinQty'): '最低数量',
    ('SpecialOffer', 'MaxQty'): '最高数量',
    ('StateProvince', 'IsOnlyStateProvinceFlag'): '是否唯一州省标志',
    ('TransactionHistory', 'ReferenceOrderID'): '关联订单编号',
    ('TransactionHistory', 'ReferenceOrderLineID'): '关联订单行号',
    ('TransactionHistory', 'ActualCost'): '实际成本',
    ('TransactionHistoryArchive', 'ReferenceOrderID'): '关联订单编号',
    ('TransactionHistoryArchive', 'ReferenceOrderLineID'): '关联订单行号',
    ('TransactionHistoryArchive', 'ActualCost'): '实际成本',
    ('Vendor', 'CreditRating'): '信用评级',
    ('Vendor', 'PreferredVendorStatus'): '首选供应商标志',
    ('Vendor', 'ActiveFlag'): '是否在用标志',
    ('Vendor', 'PurchasingWebServiceURL'): '采购Web服务URL',
    ('WorkOrder', 'StockedQty'): '入库数量',
    ('WorkOrder', 'ScrappedQty'): '报废数量',
    ('WorkOrderRouting', 'OperationSequence'): '工序顺序',
    ('WorkOrderRouting', 'ScheduledStartDate'): '计划开始日期',
    ('WorkOrderRouting', 'ScheduledEndDate'): '计划结束日期',
    ('WorkOrderRouting', 'PlannedCost'): '计划成本',
    ('WorkOrderRouting', 'ActualStartDate'): '实际开始日期',
    ('WorkOrderRouting', 'ActualEndDate'): '实际结束日期',
    ('WorkOrderRouting', 'ActualResourceHrs'): '实际资源工时',
    ('WorkOrderRouting', 'ActualCost'): '实际成本',
}

# (原名表, 原名列) -> 中文 value_description(BIRD 标注员踩坑后写下的避坑注释)
# 仅收「真·语义陷阱」:枚举/标志解码、NULL/0 特殊含义、计算列、业务规则。
# 流水账(主键自增/Default:getdate 等)无语义价值,不收。
VALUE_DESC_TRANSLATION = {
    ('BillOfMaterials', 'EndDate'): 'NULL=当前生效,非空=已失效',
    ('Address', 'AddressLine2'): 'NULL=地址较短(无第二行)',
    ('Document', 'DocumentSummary'): 'NULL=私密文档',
    ('ProductVendor', 'OnOrderQty'): '0=缺货',
    ('SalesPerson', 'Bonus'): '0=未达配额',
    ('Document', 'Status'): '1=待审批,2=已批准,3=已作废',
    ('Document', 'FolderFlag'): '0=文件夹,1=文档',
    ('Employee', 'MaritalStatus'): 'M=已婚,S=单身',
    ('Employee', 'Gender'): 'M=男,F=女',
    ('Employee', 'CurrentFlag'): '0=离职,1=在职',
    ('Employee', 'SalariedFlag'): '0=时薪,1=月薪',
    ('EmployeePayHistory', 'PayFrequency'): '1=月薪,2=双周薪',
    ('Person', 'PersonType'): 'SC=门店联系人,IN=个人客户,SP=销售员,EM=员工,VC=供应商联系人,GC=一般联系人',
    ('Person', 'NameStyle'): '0=西方(名在前),1=东方(姓在前)',
    ('Person', 'EmailPromotion'): '0=不接收,1=接收,2=接收(含合作方)',
    ('Product', 'MakeFlag'): '0=外购,1=自制',
    ('Product', 'FinishedGoodsFlag'): '0=非成品,1=成品(可售)',
    ('Product', 'ProductLine'): 'R=公路,M=山地,T=旅行,S=标准',
    ('Product', 'Class'): 'H=高,M=中,L=低',
    ('Product', 'Style'): 'W=女式,M=男式,U=通用',
    ('PurchaseOrderHeader', 'Status'): '1=待定,2=已批准,3=已拒绝,4=已完成',
    ('SalesOrderHeader', 'Status'): '1=待定,2=已批准,3=已拒绝,4=已完成',
    ('SalesTaxRate', 'TaxType'): '1=零售,2=批发,3=全部',
    ('TransactionHistory', 'TransactionType'): 'W=工单,S=销售订单,P=采购订单',
    ('TransactionHistoryArchive', 'TransactionType'): 'W=工单,S=销售订单,P=采购订单',
    ('Vendor', 'CreditRating'): '1=优秀,2=良好,3=中上,4=一般,5=较差',
    ('Vendor', 'PreferredVendorStatus'): '0=非首选,1=首选',
    ('Vendor', 'ActiveFlag'): '0=停用,1=在用',
    ('StateProvince', 'IsOnlyStateProvinceFlag'): '0=有州省代码,1=无州省代码(用国家代码)',
    ('ProductProductPhoto', 'Primary'): '0=非主图,1=主图',
    ('ProductReview', 'Rating'): '1-5,5最高',
    ('PurchaseOrderDetail', 'LineTotal'): '计算列:订购数量×单价',
    ('PurchaseOrderHeader', 'SubTotal'): '计算列:明细行总额之和',
    ('PurchaseOrderHeader', 'TotalDue'): '计算列:小计+税+运费',
    ('WorkOrder', 'StockedQty'): '计算列:订单量-报废量',
    ('Customer', 'AccountNumber'): "计算列:'AW'+客户编号",
    ('Employee', 'OrganizationLevel'): '计算列:组织层级深度',
    ('Document', 'DocumentLevel'): '计算列:文档层级深度',
    ('Product', 'ListPrice'): '利润=标价-标准成本',
    ('ProductVendor', 'LastReceiptCost'): '净利(profit on net)=上次收货成本-标准价',
    ('ProductVendor', 'StandardPrice'): '区别于产品StandardCost(标准成本);净利(profit on net)=上次收货成本-此值',
    ('ProductVendor', 'AverageLeadTime'): '单位:天',
    ('SpecialOffer', 'EndDate'): '促销期=结束日期-开始日期',
    ('SalesTaxRate', 'Name'): "含'+'=多重税",
}

# 词 -> 中文
WORD_GLOSS = {
    'id': '编号', 'name': '名称', 'date': '日期', 'time': '时间', 'flag': '标志',
    'code': '代码', 'number': '编号', 'qty': '数量', 'quantity': '数量',
    'price': '价格', 'cost': '成本', 'amount': '金额', 'total': '总计',
    'sub': '小计', 'tax': '税', 'freight': '运费', 'due': '应付',
    'description': '描述', 'comment': '备注', 'color': '颜色', 'size': '尺寸', 'weight': '重量',
    'email': '邮箱', 'phone': '电话', 'address': '地址', 'city': '城市', 'state': '州',
    'province': '省', 'country': '国家', 'region': '地区', 'postal': '邮编',
    'first': '名', 'middle': '中间名', 'title': '头衔', 'suffix': '后缀',
    'start': '开始', 'end': '结束', 'modified': '修改', 'created': '创建',
    'order': '订单', 'sales': '销售', 'purchase': '采购', 'customer': '客户',
    'person': '人员', 'employee': '员工', 'vendor': '供应商', 'product': '产品',
    'bill': '物料', 'material': '材料', 'component': '组件', 'assembly': '装配',
    'unit': '单位', 'measure': '计量', 'subcategory': '子类', 'category': '类别',
    'model': '型号', 'inventory': '库存', 'stock': '库存', 'safety': '安全',
    'reorder': '再订货', 'point': '点', 'make': '制造', 'finished': '成品', 'goods': '货物',
    'class': '等级', 'style': '款式', 'line': '产品线', 'type': '类型', 'group': '组',
    'credit': '信用', 'card': '卡', 'exp': '到期', 'month': '月', 'year': '年',
    'account': '账户', 'standard': '标准', 'list': '标价', 'days': '天数',
    'manufacture': '制造', 'territory': '区域', 'quota': '配额', 'bonus': '奖金',
    'commission': '佣金', 'salesytd': '年初至今销售额', 'saleslastyear': '去年销售额',
    'revision': '修订', 'business': '业务', 'entity': '实体', 'contact': '联系',
    'culture': '文化', 'currency': '货币', 'job': '工作', 'candidate': '求职者',
    'candidate': '求职者', 'pay': '薪资', 'history': '历史', 'work': '工单',
    'routing': '路由', 'transaction': '事务', 'archive': '归档', 'scrap': '报废',
    'reason': '原因', 'location': '位置', 'shift': '班次', 'ship': '运输', 'method': '方式',
    'shopping': '购物', 'cart': '购物车', 'item': '条目', 'special': '特殊', 'offer': '优惠',
    'unitmeasure': '计量单位', 'state': '州', 'countryregion': '国家地区', 'addressline1': '地址第一行',
    'addressline2': '地址第二行', 'postalcode': '邮编', 'onlineorderflag': '在线下单标记',
    'finishedgoodsflag': '成品标记', 'makeflag': '自制标记', 'safetystocklevel': '安全库存水平',
    'reorderpoint': '再订货点', 'daystomanufacture': '制造天数', 'sellstartdate': '开售日期',
    'sellenddate': '停售日期', 'discontinueddate': '停产日期', 'productsubcategoryid': '产品子类编号',
    'productmodelid': '产品型号编号', 'sizeunitmeasurecode': '尺寸单位代码', 'weightunitmeasurecode': '重量单位代码',
    'salespersonid': '销售员编号', 'territoryid': '区域编号', 'customerid': '客户编号',
    'salesorderid': '销售订单编号', 'salesorderdetailid': '销售订单明细编号', 'productid': '产品编号',
    'purchaseorderid': '采购订单编号', 'purchaseorderdetailid': '采购订单明细编号',
    'workorderid': '工单编号', 'vendorid': '供应商编号', 'businessentityid': '业务实体编号',
    'personid': '人员编号', 'storeid': '门店编号', 'creditcardid': '信用卡编号',
    'currencyrateid': '汇率编号', 'departmentid': '部门编号', 'shiftid': '班次编号',
    'emailaddressid': '邮箱编号', 'phonenumbertypeid': '电话类型编号', 'addresstypeid': '地址类型编号',
    'contacttypeid': '联系类型编号', 'documentid': '文档编号', 'locationid': '位置编号',
    'productcategoryid': '产品大类编号', 'unitmeasurecode': '计量单位代码', 'countryregioncode': '国家地区代码',
    'stateprovincecode': '州省代码', 'stateprovinceid': '州省编号', 'addressid': '地址编号',
    'billtoaddressid': '账单地址编号', 'shiptoaddressid': '收货地址编号', 'shipmethodid': '运输方式编号',
}


def split_camel(s):
    s = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', s)
    s = re.sub(r'(?<=[A-Z])(?=[A-Z][a-z])', ' ', s)
    return s.split()


STOPWORDS = {'of', 'for', 'and', 'the', 'to', 'in', 'by', 'a', 'an'}


def gloss_col(table, name):
    key = (table, name)
    if key in TABLE_FIELD_OVERRIDE:
        return TABLE_FIELD_OVERRIDE[key]
    if name in FIELD_OVERRIDE:
        return FIELD_OVERRIDE[name]
    low = name.lower()
    if low in WORD_GLOSS:
        return WORD_GLOSS[low]
    parts = []
    for w in split_camel(name):
        wl = w.lower()
        if wl in STOPWORDS:
            continue
        g = WORD_GLOSS.get(wl) or WORD_GLOSS.get(wl.rstrip('s')) or wl
        parts.append(g)
    return ''.join(parts) if parts else name


def short_name(desc):
    s = desc.split(',')[0]
    s = re.sub(r'[（(].*?[)）]', '', s)
    for suf in ('关联表', '维度表', '事实表', '历史表', '明细表', '头表', '清单表', '主表', '维度', '表'):
        if s.endswith(suf):
            s = s[:-len(suf)]
            break
    return s or desc.split(',')[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--map', default='obfuscation_map.json')
    ap.add_argument('--desc-dir', default='database_description')
    ap.add_argument('--out', default='descriptions.json')
    args = ap.parse_args()

    omap = json.load(open(args.map))

    # 读 BIRD 英文描述(备用参考, 不直接用)
    bird = {}
    for fn in sorted(os.listdir(args.desc_dir)):
        if not fn.lower().endswith('.csv'):
            continue
        table = os.path.splitext(fn)[0]
        raw = open(os.path.join(args.desc_dir, fn), 'rb').read()
        for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
            try:
                text = raw.decode(enc); break
            except UnicodeDecodeError:
                continue
        d = {}
        for row in csv.DictReader(io.StringIO(text)):
            d[row['original_column_name'].strip()] = row.get('column_description', '').strip()
        bird[table] = d

    out = {}
    for table, meta in TABLE_META.items():
        typ, desc = meta
        m = omap[table]
        fields = {}
        for orig_col, obf_col in m['columns'].items():
            if obf_col.startswith('ref'):
                # ref 列: 优先 REF_OVERRIDE, 否则用目标表中文短名
                if orig_col.lower() in REF_OVERRIDE:
                    fields[orig_col] = REF_OVERRIDE[orig_col.lower()]
                else:
                    fk = next((f for f in m['fks'] if f['from_col'] == obf_col), None)
                    if fk:
                        tgt_orig = {v['abbrev']: k for k, v in omap.items()}[fk['to_table']]
                        fields[orig_col] = f"{short_name(TABLE_META[tgt_orig][1])}编号"
                    else:
                        fields[orig_col] = '关联编号'
            else:
                g = gloss_col(table, orig_col)
                vd = VALUE_DESC_TRANSLATION.get((table, orig_col))
                fields[orig_col] = g + (f"({vd})" if vd else "")
        out[table] = {"type": typ, "desc": desc, "fields": fields}

    json.dump(out, open(args.out, 'w'), ensure_ascii=False, indent=2)
    # 统计
    from collections import Counter
    print("表:", len(out), "类型:", dict(Counter(v['type'] for v in out.values())))
    nf = sum(len(v['fields']) for v in out.values())
    print("字段:", nf)
    for t in ['Customer', 'SalesOrderHeader', 'BillOfMaterials']:
        print(f"\n[{t}] {out[t]['type']} | {out[t]['desc']}")
        for c, g in list(out[t]['fields'].items())[:6]:
            print(f"  {c} -> {g}")


if __name__ == '__main__':
    main()
