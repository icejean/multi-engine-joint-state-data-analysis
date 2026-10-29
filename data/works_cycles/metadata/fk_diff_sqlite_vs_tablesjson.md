# FK 差异清单：SQLite 声明 vs train_tables.json

- SQLite 声明 FK：**87 条**
- train_tables.json foreign_keys：**61 条**
- 差异（SQLite 有、tables.json 无）：**26 条**
- tables.json 有、SQLite 无：0 条

## 差异明细（SQLite 独有，共 26 条）

| 源表 | 源列 | 引用表 | 引用列 |
|---|---|---|---|
| Address | StateProvinceID | StateProvince | StateProvinceID |
| BillOfMaterials | ComponentID | Product | ProductID |
| BillOfMaterials | ProductAssemblyID | Product | ProductID |
| BillOfMaterials | UnitMeasureCode | UnitMeasure | UnitMeasureCode |
| CurrencyRate | FromCurrencyCode | Currency | CurrencyCode |
| CurrencyRate | ToCurrencyCode | Currency | CurrencyCode |
| Document | Owner | Employee | BusinessEntityID |
| EmployeeDepartmentHistory | BusinessEntityID | Employee | BusinessEntityID |
| EmployeeDepartmentHistory | DepartmentID | Department | DepartmentID |
| EmployeeDepartmentHistory | ShiftID | Shift | ShiftID |
| EmployeePayHistory | BusinessEntityID | Employee | BusinessEntityID |
| JobCandidate | BusinessEntityID | Employee | BusinessEntityID |
| Product | ProductModelID | ProductModel | ProductModelID |
| Product | ProductSubcategoryID | ProductSubcategory | ProductSubcategoryID |
| Product | SizeUnitMeasureCode | UnitMeasure | UnitMeasureCode |
| Product | WeightUnitMeasureCode | UnitMeasure | UnitMeasureCode |
| SalesOrderHeader | BillToAddressID | Address | AddressID |
| SalesOrderHeader | CreditCardID | CreditCard | CreditCardID |
| SalesOrderHeader | CurrencyRateID | CurrencyRate | CurrencyRateID |
| SalesOrderHeader | CustomerID | Customer | CustomerID |
| SalesOrderHeader | SalesPersonID | SalesPerson | BusinessEntityID |
| SalesOrderHeader | ShipMethodID | ShipMethod | ShipMethodID |
| SalesOrderHeader | ShipToAddressID | Address | AddressID |
| SalesOrderHeader | TerritoryID | SalesTerritory | TerritoryID |
| StateProvince | CountryRegionCode | CountryRegion | CountryRegionCode |
| StateProvince | TerritoryID | SalesTerritory | TerritoryID |
