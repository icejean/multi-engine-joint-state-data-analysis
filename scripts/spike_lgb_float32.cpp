// spike_lgb_float32.cpp — 冒烟测试：验证 LightGBM C API float32 直通道
//
// 目标（对应 spec 的核心风险点）：
//   合成 float32 数据 → LGBM_DatasetCreateFromMat(FLOAT32) 建全量 Dataset
//   → LGBM_DatasetSetField(FLOAT32 label) → LGBM_DatasetGetSubset 切 train/test
//   → LGBM_BoosterUpdateOneIter 训练 → LGBM_BoosterPredictForMat(FLOAT32) 预测 → RMSE
// 全程数据不经过 R double；RMSE 收敛到噪声量级即证明 float32 直通道成立。
//
// 链接：R 侧 PKG_LIBS 指向 lightgbm.so（见 run_spike_lgb_float32.R）
//
// 关键签名坑（实测 4.7.0）：
//   LGBM_BoosterPredictForMat 是 12 参数：(handle, data, data_type, nrow, ncol,
//   is_row_major, predict_type, start_iteration, num_iteration(int), parameter,
//   out_len(int64_t*), out_result(double*))。漏掉 start_iteration / 类型写错会
//   静默预测出基分数（无树贡献）。

// [[Rcpp::plugins(cpp11)]]
#include <Rcpp.h>
#include <cstdint>
#include <vector>
#include <cmath>
#include <string>

// ---- LightGBM C API 常量（c_api.h 不在已装包内，手动声明；值与 Python basic.py 对齐） ----
#define C_API_DTYPE_FLOAT32 0
#define C_API_DTYPE_FLOAT64 1
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

// [[Rcpp::export]]
Rcpp::List spike_lgb_float32(int n = 2000, int nrounds = 100, int seed = 42) {
  const int nfeat = 5;

  // 确定性 LCG 生成合成数据：y = 2*x1 - 3*x2 + 0.5*x3 + 0.1*噪声
  uint32_t s = (uint32_t)seed;
  auto rnd = [&]() {
    s = s * 1664525u + 1013904223u;
    return ((float)(s >> 8) / 16777216.0f) * 2.0f - 1.0f;
  };
  std::vector<float> X((size_t)n * nfeat);
  std::vector<float> y(n);
  for (int i = 0; i < n; i++) {
    float x1 = rnd(), x2 = rnd(), x3 = rnd(), x4 = rnd(), x5 = rnd();
    X[(size_t)i * nfeat + 0] = x1; X[(size_t)i * nfeat + 1] = x2; X[(size_t)i * nfeat + 2] = x3;
    X[(size_t)i * nfeat + 3] = x4; X[(size_t)i * nfeat + 4] = x5;
    y[i] = 2.0f * x1 - 3.0f * x2 + 0.5f * x3 + 0.1f * rnd();
  }

  // 1) 全量 float32 Dataset（特征 float32，label float32）
  DatasetHandle full = nullptr;
  check(LGBM_DatasetCreateFromMat(X.data(), C_API_DTYPE_FLOAT32, n, nfeat,
                                  C_API_IS_ROW_MAJOR, "", nullptr, &full), "CreateFromMat");
  check(LGBM_DatasetSetField(full, "label", y.data(), n, C_API_DTYPE_FLOAT32), "SetField");

  // 2) GetSubset 切 train/test（不建第二份特征矩阵）
  int ntrain = (int)(n * 0.8);
  int ntest = n - ntrain;
  std::vector<int32_t> tr_idx(ntrain), te_idx(ntest);
  for (int i = 0; i < ntrain; i++) tr_idx[i] = i;
  for (int i = 0; i < ntest; i++) te_idx[i] = ntrain + i;
  DatasetHandle train_ds = nullptr, test_ds = nullptr;
  check(LGBM_DatasetGetSubset(full, tr_idx.data(), ntrain, "", &train_ds), "GetSubset(train)");
  check(LGBM_DatasetGetSubset(full, te_idx.data(), ntest, "", &test_ds), "GetSubset(test)");

  // 3) 训练（在 train 子集上）
  std::string params = "objective=regression num_threads=1 verbosity=-1 seed=" + std::to_string(seed);
  BoosterHandle booster = nullptr;
  check(LGBM_BoosterCreate(train_ds, params.c_str(), &booster), "BoosterCreate");
  for (int i = 0; i < nrounds; i++) {
    int finished = 0;
    check(LGBM_BoosterUpdateOneIter(booster, &finished), "UpdateOneIter");
  }

  // 4) 预测（float32 直通；start_iteration=0, num_iteration=-1 表示用全部树）
  int64_t out_len = 0;
  std::vector<double> pred(ntest + 64);
  check(LGBM_BoosterPredictForMat(booster, X.data() + (size_t)ntrain * nfeat,
                                  C_API_DTYPE_FLOAT32, ntest, nfeat, C_API_IS_ROW_MAJOR,
                                  C_API_PREDICT_NORMAL, 0, -1, "", &out_len, pred.data()),
        "PredictForMat");

  // 5) RMSE
  double sse = 0.0;
  for (int i = 0; i < ntest; i++) { double e = pred[i] - y[ntrain + i]; sse += e * e; }
  double rmse = std::sqrt(sse / ntest);

  LGBM_BoosterFree(booster);
  if (train_ds) LGBM_DatasetFree(train_ds);
  if (test_ds) LGBM_DatasetFree(test_ds);
  LGBM_DatasetFree(full);

  return Rcpp::List::create(
    Rcpp::Named("rmse") = rmse,
    Rcpp::Named("n") = n, Rcpp::Named("ntrain") = ntrain, Rcpp::Named("ntest") = ntest,
    Rcpp::Named("nrounds") = nrounds, Rcpp::Named("out_len") = (double)out_len);
}
