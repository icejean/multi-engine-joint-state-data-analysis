// gbdt_float.cpp — 通用「float32 直读 + LightGBM 训练/预测」核心
//
// 职责（spec §1.1）：加载 parquet → float32（不落 R double）→ 切分 → LightGBM → 训练/预测。
// 预处理通过 `preprocess` 逐块回调注入（无状态变换）；有状态（StandardScaler）走预处理文件。
//
// 签名坑见 spec §6.1：PredictForMat 12 参数（含 start_iteration）、label 只吃 FLOAT32；
// arrow 编译坑：要 C++17，OpenFile/GetRecordBatchReader 返回 Result<unique_ptr>。

// [[Rcpp::plugins(cpp17)]]
#include <Rcpp.h>
#include <cstdint>
#include <vector>
#include <string>
#include <cmath>
#include <cstring>
#include <memory>
#include <algorithm>
#include <random>

#include <arrow/api.h>
#include <arrow/io/api.h>
#include <parquet/arrow/reader.h>

// ---- LightGBM C API ----
#define C_API_DTYPE_FLOAT32 0
#define C_API_IS_ROW_MAJOR  1
#define C_API_PREDICT_NORMAL 0
typedef void* DatasetHandle;
typedef void* BoosterHandle;

extern "C" {
int LGBM_DatasetCreateFromMat(const void* data, int data_type, int32_t nrow, int32_t ncol,
                              int is_row_major, const char* parameters, const void* reference,
                              DatasetHandle* out);
int LGBM_DatasetSetField(DatasetHandle handle, const char* field_name, const void* data,
                         int num_element, int type);
int LGBM_DatasetGetSubset(DatasetHandle handle, const int32_t* used_row_indices,
                          int32_t num_used_row_indices, const char* parameters, DatasetHandle* out);
int LGBM_BoosterCreate(DatasetHandle train_data, const char* parameters, BoosterHandle* out);
int LGBM_BoosterUpdateOneIter(BoosterHandle handle, int* is_finished);
int LGBM_BoosterPredictForMat(BoosterHandle handle, const void* data, int data_type,
                              int32_t nrow, int32_t ncol, int is_row_major, int predict_type,
                              int start_iteration, int num_iteration, const char* parameter,
                              int64_t* out_len, double* out_result);
int LGBM_BoosterFree(BoosterHandle handle);
int LGBM_DatasetFree(DatasetHandle handle);
const char* LGBM_GetLastError(void);
}

static void check(int ret, const char* ctx) {
  if (ret != 0) Rcpp::stop("%s failed (code %d): %s", ctx, ret, LGBM_GetLastError());
}

// ---- 累积结果 ----
struct Loaded {
  std::vector<float> X;        // N*P 行主序 float32
  std::vector<float> y;        // N float32
  std::vector<double> split;   // N（切分列值）
  bool has_split = false;
  int64_t nrow = 0, nfeat = 0;
};

// ---- arrow RecordBatch → R data.frame（所有列转 numeric/double） ----
static Rcpp::DataFrame batch_to_df(const std::shared_ptr<arrow::RecordBatch>& batch) {
  int ncol = batch->num_columns();
  Rcpp::List cols(ncol);
  Rcpp::CharacterVector names(ncol);
  for (int i = 0; i < ncol; i++) {
    names[i] = batch->column_name(i);
    auto col = batch->column(i);
    int64_t n = col->length();
    Rcpp::NumericVector v(n);
    if (col->type_id() == arrow::Type::FLOAT) {
      auto a = std::static_pointer_cast<arrow::FloatArray>(col);
      for (int64_t r = 0; r < n; r++) v[r] = a->Value(r);
    } else if (col->type_id() == arrow::Type::DOUBLE) {
      auto a = std::static_pointer_cast<arrow::DoubleArray>(col);
      for (int64_t r = 0; r < n; r++) v[r] = a->Value(r);
    } else if (col->type_id() == arrow::Type::INT64) {
      auto a = std::static_pointer_cast<arrow::Int64Array>(col);
      for (int64_t r = 0; r < n; r++) v[r] = (double)a->Value(r);
    } else if (col->type_id() == arrow::Type::INT32) {
      auto a = std::static_pointer_cast<arrow::Int32Array>(col);
      for (int64_t r = 0; r < n; r++) v[r] = (double)a->Value(r);
    } else if (col->type_id() == arrow::Type::BOOL) {
      auto a = std::static_pointer_cast<arrow::BooleanArray>(col);
      for (int64_t r = 0; r < n; r++) v[r] = a->Value(r) ? 1.0 : 0.0;
    } else {
      Rcpp::stop("batch_to_df: unsupported column type for '%s'", std::string(names[i]).c_str());
    }
    cols[i] = v;
  }
  cols.attr("names") = names;
  return Rcpp::DataFrame(cols);
}

// ---- 回调路径：逐块转 R data.frame → preprocess → 提取 float32 特征/target/split ----
static void load_with_preprocess(const std::string& path, const std::string& target,
                                 const std::string& split_col,
                                 Rcpp::Function preprocess, int batch_size, Loaded& out) {
  Rcpp::Function gc_fn("gc");   // 每块处理后强制 GC，防 R 临时对象堆积
  std::shared_ptr<arrow::io::ReadableFile> infile;
  { auto r = arrow::io::ReadableFile::Open(path);
    if (!r.ok()) Rcpp::stop("ReadableFile::Open: %s", r.status().message().c_str());
    infile = r.ValueOrDie(); }
  std::unique_ptr<parquet::arrow::FileReader> reader;
  { auto r = parquet::arrow::OpenFile(infile, arrow::default_memory_pool());
    if (!r.ok()) Rcpp::stop("parquet OpenFile: %s", r.status().message().c_str());
    reader = std::move(r).ValueOrDie(); }
  reader->set_batch_size(batch_size);   // 控单块 R data.frame 大小（防 row group 过大撑爆内存）
  std::unique_ptr<arrow::RecordBatchReader> br;
  { auto r = reader->GetRecordBatchReader();
    if (!r.ok()) Rcpp::stop("GetRecordBatchReader: %s", r.status().message().c_str());
    br = std::move(r).ValueOrDie(); }

  std::shared_ptr<arrow::RecordBatch> batch;
  while (true) {
    { auto r = br->Next();
      if (!r.ok()) Rcpp::stop("Next: %s", r.status().message().c_str());
      batch = r.ValueOrDie(); }
    if (batch == nullptr) break;

    Rcpp::DataFrame df = preprocess(batch_to_df(batch));   // 回调（R 层，逐块 double 临时）
    Rcpp::CharacterVector nm = df.names();
    int64_t n = df.nrows();
    if (n == 0) continue;

    // 特征列 = 所有 numeric 列 除 target/split_col
    std::vector<int> fidx;
    for (int i = 0; i < nm.size(); i++) {
      std::string s = Rcpp::as<std::string>(nm[i]);
      if (s != target && s != split_col) fidx.push_back(i);
    }
    int P = (int)fidx.size();
    if (out.nfeat == 0) {
      out.nfeat = P;
      // 首块确定 P 后预分配，避免 resize 重分配时旧+新两份拷贝把峰值翻倍
      int64_t total_rows = reader->parquet_reader()->metadata()->num_rows();
      if (total_rows > 0) {
        out.X.reserve((size_t)total_rows * P);
        out.y.reserve((size_t)total_rows);
        if (!split_col.empty()) out.split.reserve((size_t)total_rows);
      }
    }
    if (P != out.nfeat) Rcpp::stop("preprocess 输出特征数不一致");

    int64_t base = out.nrow;
    out.nrow += n;
    out.X.resize(out.X.size() + (size_t)n * P);
    out.y.resize(out.y.size() + (size_t)n);
    if (!split_col.empty()) out.split.resize(out.split.size() + (size_t)n);

    // target 列索引
    int tidx = -1;
    for (int i = 0; i < nm.size(); i++) if (Rcpp::as<std::string>(nm[i]) == target) { tidx = i; break; }
    if (tidx < 0) Rcpp::stop("preprocess 输出缺 target 列 '%s'", target.c_str());
    Rcpp::NumericVector tv = df[tidx];

    // split 列索引（可选）
    int sidx = -1;
    Rcpp::NumericVector sv;
    if (!split_col.empty()) {
      for (int i = 0; i < nm.size(); i++) if (Rcpp::as<std::string>(nm[i]) == split_col) { sidx = i; break; }
      if (sidx < 0) Rcpp::stop("preprocess 输出缺 split 列 '%s'", split_col.c_str());
      sv = df[sidx];
    }

    // 预提取所有特征列（一次），避免在行循环里反复取列
    std::vector<Rcpp::NumericVector> fcols(P);
    for (int c = 0; c < P; c++) fcols[c] = df[fidx[c]];

    for (int64_t r = 0; r < n; r++) {
      size_t dst = (size_t)(base + r) * P;
      for (int c = 0; c < P; c++) out.X[dst + c] = (float)fcols[c][r];
      out.y[base + r] = (float)tv[r];
      if (sidx >= 0) out.split[base + r] = sv[r];
    }
    gc_fn();   // 回收本块的 df/POSIXlt 等 R 临时对象，防 arena 无界增长
  }
  out.has_split = !split_col.empty();
}

// ---- 直读路径（无回调，显式特征列） ----
static void load_parquet(const std::string& path, const std::vector<std::string>& feats,
                         const std::string& target, const std::string& split_col,
                         int batch_size, Loaded& out) {
  std::shared_ptr<arrow::io::ReadableFile> infile;
  { auto r = arrow::io::ReadableFile::Open(path);
    if (!r.ok()) Rcpp::stop("ReadableFile::Open: %s", r.status().message().c_str());
    infile = r.ValueOrDie(); }
  std::unique_ptr<parquet::arrow::FileReader> reader;
  { auto r = parquet::arrow::OpenFile(infile, arrow::default_memory_pool());
    if (!r.ok()) Rcpp::stop("parquet OpenFile: %s", r.status().message().c_str());
    reader = std::move(r).ValueOrDie(); }
  reader->set_batch_size(batch_size);   // 控单块 R data.frame 大小（防 row group 过大撑爆内存）
  std::unique_ptr<arrow::RecordBatchReader> br;
  { auto r = reader->GetRecordBatchReader();
    if (!r.ok()) Rcpp::stop("GetRecordBatchReader: %s", r.status().message().c_str());
    br = std::move(r).ValueOrDie(); }

  const int P = (int)feats.size();
  out.nfeat = P;
  // 预分配，避免 resize 重分配时旧+新两份拷贝把峰值翻倍
  int64_t total_rows = reader->parquet_reader()->metadata()->num_rows();
  if (total_rows > 0) {
    out.X.reserve((size_t)total_rows * P);
    out.y.reserve((size_t)total_rows);
    if (!split_col.empty()) out.split.reserve((size_t)total_rows);
  }

  std::shared_ptr<arrow::RecordBatch> batch;
  while (true) {
    { auto r = br->Next();
      if (!r.ok()) Rcpp::stop("Next: %s", r.status().message().c_str());
      batch = r.ValueOrDie(); }
    if (batch == nullptr) break;

    int64_t n = batch->num_rows();
    std::vector<const float*> fp(P, nullptr);
    std::vector<const double*> dp(P, nullptr);
    std::vector<bool> is_f(P, false);
    for (int c = 0; c < P; c++) {
      auto col = batch->GetColumnByName(feats[c]);
      if (col == nullptr) Rcpp::stop("feature column not found: %s", feats[c].c_str());
      if (col->type_id() == arrow::Type::FLOAT) { fp[c] = std::static_pointer_cast<arrow::FloatArray>(col)->raw_values(); is_f[c] = true; }
      else if (col->type_id() == arrow::Type::DOUBLE) { dp[c] = std::static_pointer_cast<arrow::DoubleArray>(col)->raw_values(); }
      else Rcpp::stop("feature column '%s' 不是 float/double", feats[c].c_str());
    }
    auto tcol = batch->GetColumnByName(target);
    const float* tf = nullptr; const double* td = nullptr; bool t_is_f = false;
    if (tcol->type_id() == arrow::Type::FLOAT) { tf = std::static_pointer_cast<arrow::FloatArray>(tcol)->raw_values(); t_is_f = true; }
    else if (tcol->type_id() == arrow::Type::DOUBLE) { td = std::static_pointer_cast<arrow::DoubleArray>(tcol)->raw_values(); }
    else Rcpp::stop("target 不是 float/double");

    const int64_t* si = nullptr; const int32_t* s32 = nullptr; const double* sd = nullptr; int stype = 0;
    if (!split_col.empty()) {
      auto scol = batch->GetColumnByName(split_col);
      if (scol->type_id() == arrow::Type::INT64) { si = std::static_pointer_cast<arrow::Int64Array>(scol)->raw_values(); stype = 1; }
      else if (scol->type_id() == arrow::Type::INT32) { s32 = std::static_pointer_cast<arrow::Int32Array>(scol)->raw_values(); stype = 2; }
      else if (scol->type_id() == arrow::Type::DOUBLE) { sd = std::static_pointer_cast<arrow::DoubleArray>(scol)->raw_values(); stype = 3; }
    }

    int64_t base = out.nrow;
    out.nrow += n;
    out.X.resize(out.X.size() + (size_t)n * P);
    out.y.resize(out.y.size() + (size_t)n);
    if (stype) out.split.resize(out.split.size() + (size_t)n);
    for (int64_t r = 0; r < n; r++) {
      size_t dst = (size_t)(base + r) * P;
      for (int c = 0; c < P; c++) out.X[dst + c] = is_f[c] ? fp[c][r] : (float)dp[c][r];
      out.y[base + r] = t_is_f ? tf[r] : (float)td[r];
      if (stype == 1) out.split[base + r] = (double)si[r];
      else if (stype == 2) out.split[base + r] = (double)s32[r];
      else if (stype == 3) out.split[base + r] = sd[r];
    }
  }
  out.has_split = !split_col.empty();
}

static std::string params_to_str(const Rcpp::List& params) {
  std::string s;
  Rcpp::CharacterVector nm = params.names();
  for (int i = 0; i < params.size(); i++) {
    if (i) s += " ";
    s += Rcpp::as<std::string>(nm[i]) + "=";
    SEXP v = params[i];
    if (Rf_isInteger(v)) s += std::to_string(Rcpp::as<int>(v));
    else if (Rf_isReal(v)) s += std::to_string(Rcpp::as<double>(v));
    else if (Rf_isLogical(v)) s += (Rcpp::as<bool>(v) ? "true" : "false");
    else s += Rcpp::as<std::string>(v);
  }
  return s;
}

// StandardScaler：fit train 列均值/方差（忽略 NaN，ddof=0 对齐 numpy）→ 全量 float32 原地变换 → NaN→0
static void standardize(Loaded& d, const std::vector<int32_t>& tr_idx) {
  const int64_t N = d.nrow, P = d.nfeat;
  const size_t nt = tr_idx.size();
  std::vector<double> mean(P), sd(P);
  for (int64_t c = 0; c < P; c++) {
    double sum = 0; size_t cnt = 0;
    for (size_t i = 0; i < nt; i++) {
      float v = d.X[(size_t)tr_idx[i] * P + c];
      if (!std::isnan(v)) { sum += v; cnt++; }
    }
    double m = cnt ? sum / cnt : 0.0;
    double ss = 0;
    for (size_t i = 0; i < nt; i++) {
      float v = d.X[(size_t)tr_idx[i] * P + c];
      if (!std::isnan(v)) { double e = v - m; ss += e * e; }
    }
    double s = cnt > 1 ? std::sqrt(ss / cnt) : 1.0;
    if (!(s > 1e-12)) s = 1.0;
    mean[c] = m; sd[c] = s;
  }
  for (int64_t i = 0; i < N; i++)
    for (int64_t c = 0; c < P; c++) {
      float v = d.X[(size_t)i * P + c];
      d.X[(size_t)i * P + c] = std::isnan(v) ? 0.0f : (float)((v - mean[c]) / sd[c]);
    }
}

// 预测某一部分行并返回 RMSE/MAE
// 分块预测（chunk_rows 行/块）：只拷贝一块特征，不再整块 memcpy 出 n*P 副本。
// 预测逐行独立，分块与整块的结果逐位相同，不影响精度。
static double predict_rmse(BoosterHandle booster, const Loaded& d,
                           const std::vector<int32_t>& idx, double* mae_out,
                           int64_t chunk_rows = 65536) {
  const int64_t n = (int64_t)idx.size();
  const int64_t P = d.nfeat;
  if (n == 0) { if (mae_out) *mae_out = R_NaN; return R_NaN; }
  const int64_t buf_rows = std::min<int64_t>(chunk_rows, n);
  std::vector<float> X((size_t)buf_rows * P);
  std::vector<double> pred((size_t)buf_rows + 64);
  double sse = 0, sae = 0;
  for (int64_t start = 0; start < n; start += chunk_rows) {
    const int32_t m = (int32_t)std::min<int64_t>(chunk_rows, n - start);
    for (int32_t i = 0; i < m; i++)
      std::memcpy(&X[(size_t)i * P], &d.X[(size_t)idx[start + i] * P], (size_t)P * sizeof(float));
    int64_t out_len = 0;
    check(LGBM_BoosterPredictForMat(booster, X.data(), C_API_DTYPE_FLOAT32, m, (int32_t)P,
                                    C_API_IS_ROW_MAJOR, C_API_PREDICT_NORMAL, 0, -1, "",
                                    &out_len, pred.data()), "Predict");
    for (int32_t i = 0; i < m; i++) {
      double e = pred[i] - d.y[idx[start + i]];
      sse += e * e; sae += std::fabs(e);
    }
  }
  if (mae_out) *mae_out = sae / n;
  return std::sqrt(sse / n);
}

// [[Rcpp::export]]
Rcpp::List gbdt_float_fit(std::string source, std::string target,
                          Rcpp::Nullable<Rcpp::CharacterVector> features,
                          std::string split_col, Rcpp::NumericVector split_val,
                          Rcpp::Nullable<Rcpp::Function> preprocess,
                          std::string scale,
                          Rcpp::List params, int nrounds, int seed, int batch_size = 131072) {
  Loaded d;
  if (preprocess.isNotNull()) {
    load_with_preprocess(source, target, split_col, Rcpp::as<Rcpp::Function>(preprocess), batch_size, d);
  } else {
    std::vector<std::string> feats = Rcpp::as<std::vector<std::string>>(features);
    load_parquet(source, feats, target, split_col, batch_size, d);
  }
  const int64_t N = d.nrow, P = d.nfeat;

  // 切分：split_val 为阈值向量（有 split_col，升序）或比例向量（无 split_col，非累积）
  std::vector<int32_t> tr_idx, va_idx, te_idx;
  std::vector<double> sv = Rcpp::as<std::vector<double>>(split_val);
  if (d.has_split) {
    for (int64_t i = 0; i < N; i++) {
      double v = d.split[i];
      if (sv.size() >= 2 && v >= sv[1]) te_idx.push_back((int32_t)i);
      else if (sv.size() >= 1 && v >= sv[0]) va_idx.push_back((int32_t)i);
      else tr_idx.push_back((int32_t)i);
    }
  } else {
    // 按比例随机切分（seed 可复现）
    double tr_f = sv.size() >= 1 ? sv[0] : 0.8;
    double va_f = sv.size() >= 2 ? sv[1] : 0.0;
    int64_t ntr = (int64_t)(N * tr_f), nva = (int64_t)(N * va_f);
    std::vector<int32_t> perm(N);
    for (int64_t i = 0; i < N; i++) perm[i] = (int32_t)i;
    std::mt19937 rng((uint32_t)seed);
    std::shuffle(perm.begin(), perm.end(), rng);
    for (int64_t i = 0; i < N; i++) {
      int32_t r = perm[i];
      if (i < ntr) tr_idx.push_back(r);
      else if (i < ntr + nva) va_idx.push_back(r);
      else te_idx.push_back(r);
    }
  }
  // GetSubset 要求行号升序；随机切分后各桶乱序，需排序（不改变随机分配结果）
  std::sort(tr_idx.begin(), tr_idx.end());
  std::sort(va_idx.begin(), va_idx.end());
  std::sort(te_idx.begin(), te_idx.end());
  const int32_t ntrain = (int32_t)tr_idx.size(), nval = (int32_t)va_idx.size(), ntest = (int32_t)te_idx.size();

  // 列级 scaler（C++ 内置，float32 原地，像 NumPy fit/transform）
  if (scale == "standard") standardize(d, tr_idx);

  DatasetHandle full = nullptr;
  check(LGBM_DatasetCreateFromMat(d.X.data(), C_API_DTYPE_FLOAT32, (int32_t)N, (int32_t)P,
                                  C_API_IS_ROW_MAJOR, "", nullptr, &full), "CreateFromMat");
  check(LGBM_DatasetSetField(full, "label", d.y.data(), (int)N, C_API_DTYPE_FLOAT32), "SetField");
  // 训练只需要 train 子集；val/test 的预测走原始 X，不建子集数据集（省 ~0.34GB + 建立开销）。
  // GetSubset 是深拷贝（自带独立分箱数据），因此建完立刻释放 full（省 ~1.75GB）。
  DatasetHandle train_ds = nullptr;
  check(LGBM_DatasetGetSubset(full, tr_idx.data(), ntrain, "", &train_ds), "GetSubset(train)");
  LGBM_DatasetFree(full);
  full = nullptr;

  std::string ps = params_to_str(params);
  if (!ps.empty()) ps += " ";
  ps += "verbosity=-1 seed=" + std::to_string(seed);
  BoosterHandle booster = nullptr;
  check(LGBM_BoosterCreate(train_ds, ps.c_str(), &booster), "BoosterCreate");
  for (int i = 0; i < nrounds; i++) { int fin = 0; check(LGBM_BoosterUpdateOneIter(booster, &fin), "Update"); }

  double val_rmse = R_NaN, val_mae = R_NaN, test_rmse, test_mae;
  if (nval) val_rmse = predict_rmse(booster, d, va_idx, &val_mae);
  test_rmse = predict_rmse(booster, d, te_idx, &test_mae);

  // Booster 借用了 train_ds 的指针（不持有），必须先释放 booster 再释放数据集
  LGBM_BoosterFree(booster);
  if (train_ds) LGBM_DatasetFree(train_ds);

  return Rcpp::List::create(
    Rcpp::Named("rmse") = test_rmse, Rcpp::Named("mae") = test_mae,
    Rcpp::Named("val_rmse") = val_rmse, Rcpp::Named("val_mae") = val_mae,
    Rcpp::Named("n") = (double)N, Rcpp::Named("nfeat") = (double)P,
    Rcpp::Named("ntrain") = (double)ntrain, Rcpp::Named("nval") = (double)nval,
    Rcpp::Named("ntest") = (double)ntest);
}
