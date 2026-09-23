# ============================================================================
#  属性数据 · GWR 带宽区间探索（桌面端适配器）
# ----------------------------------------------------------------------------
#  约定 : JSON 配置进 → JSON 结果出，供 core/algorithms/r_runner.py 调用。
#  调用 : Rscript gwr_bandwidth.R <config.json> <output.json>
#  输入 : 一个含 N(≥2) 个数值字段的矢量数据(shapefile/GeoPackage/GeoJSON)
#         config$variables 给出候选字段，两两配对共 C(N,2) 组，口径与
#         gwr_attribute.R 完全一致（靠前的字段作 Y、靠后的作 X，共用带宽）
#  输出 : 在给定带宽序列上依次运行 gwr.basic，按配对返回每条带宽的曲线点
#         以及逐要素局部 R² / 系数 / 局部相关 / 局部误差指标（按原始要素顺序
#         对齐，被剔除的填 NA），供客户端绘制带宽曲线与逐配对局部地图。
#         第一组配对同时以平铺字段再发一份，保证既有调用方不炸。
#  依赖 : jsonlite / sf / GWmodel / sp
# ============================================================================

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2) stop("需要 config.json 和 output.json 两个参数")
config_path <- args[[1]]
output_path <- args[[2]]

# 空值兜底
`%||%` <- function(a, b) if (is.null(a) || length(a) == 0L || (length(a) == 1L && is.na(a))) b else a

write_error <- function(msg) {
  res <- list(status = "error", engine = "R 属性 GWR · 带宽探索",
              metrics = list(), message = msg, curve = list(),
              bandwidths = list(), by_pair = list(),
              local_r2 = list(), coefficient = list(),
              residual = list(), stud_residual = list())
  jsonlite::write_json(res, output_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
  quit(save = "no", status = 0)
}

if (!requireNamespace("jsonlite", quietly = TRUE)) {
  cat('{\n  "status": "error",\n  "engine": "R 属性 GWR · 带宽探索",\n  "message": "请先安装 R 包 jsonlite",\n  "curve": [],\n  "bandwidths": [],\n  "by_pair": [],\n  "local_r2": [],\n  "coefficient": [],\n  "residual": [],\n  "stud_residual": []\n}\n',
      file = output_path)
  quit(save = "no", status = 0)
}
for (pkg in c("sf", "GWmodel", "sp")) {
  if (!requireNamespace(pkg, quietly = TRUE)) write_error(sprintf("请先安装 R 包 %s", pkg))
}

config <- jsonlite::fromJSON(config_path, simplifyVector = FALSE)

SHP_PATH <- config$shp_path %||% config$data_path

# 候选字段：优先 variables 列表；旧的 x/y 两个标量按「因变量在前」还原
vars <- config$variables
if (is.null(vars) || !length(vars)) {
  fallback <- c(config$dependent_variable %||% config$y,
                config$independent_variable %||% config$x)
  fallback <- fallback[!vapply(fallback, is.null, logical(1))]
  vars <- fallback
}
vars <- as.character(unlist(vars, use.names = FALSE))
vars <- vars[!is.na(vars) & nzchar(trimws(vars))]
vars <- unique(vars)
if (length(vars) < 2) write_error("至少需要选择两个参与分析的字段(variables)")
if (is.null(SHP_PATH) || !nzchar(SHP_PATH)) write_error("缺少输入矢量路径(shp_path)")

KERNEL <- switch(config$kernel %||% "双平方核",
  "双平方核" = "bisquare", "高斯核" = "gaussian", "指数核" = "exponential",
  "bisquare" = "bisquare", "gaussian" = "gaussian", "exponential" = "exponential",
  "bisquare")
ADAPTIVE <- identical(config$bandwidth_mode %||% "最近邻个数", "最近邻个数")
PROJ_CRS <- config$crs %||%
  "+proj=aea +lat_1=25 +lat_2=47 +lat_0=0 +lon_0=105 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"

bandwidths <- config$bandwidths
if (is.null(bandwidths)) bandwidths <- seq(100, 1000, by = 100)
bandwidths <- suppressWarnings(as.integer(bandwidths))
bandwidths <- bandwidths[is.finite(bandwidths) & bandwidths > 0]
if (!length(bandwidths)) write_error("带宽序列为空或非法")

suppressPackageStartupMessages({ library(sf); library(GWmodel); library(sp) })
sf_use_s2(FALSE)

# 定位脚本所在目录，使 source("gwmv.r") 不依赖工作目录
SCRIPT_DIR <- (function() {
  a <- commandArgs(trailingOnly = FALSE)
  f <- sub("^--file=", "", a[grepl("^--file=", a)])
  if (length(f)) dirname(normalizePath(f[1])) else getwd()
})()
source(file.path(SCRIPT_DIR, "gwmv.r"))

med <- function(v) {
  v <- v[is.finite(v)]
  if (!length(v)) NA else median(v)
}
safe_rmse <- function(x) {
  x <- x[is.finite(x)]
  if (!length(x)) return(NA_real_)
  sqrt(mean(x^2))
}
json_number <- function(value) {
  if (length(value) == 0 || !is.finite(value)) NA_real_ else value
}

# 字段名 → 配对键用的安全标签（与 gwr_attribute.R 保持一致）
safe_tag <- function(value) {
  value <- gsub("[^A-Za-z0-9_.-]+", "_", value)
  value <- gsub("^_+|_+$", "", value)
  if (nzchar(value)) value else "field"
}

# GWmodel 的列名约定：gwmv 用下划线连接，gwss 用点号连接
gwmv_col <- function(prefix, first, second) paste0(prefix, "_", first, "_", second)
gwss_col <- function(first, second) paste0("Corr_", first, ".", second)

# 从 GWmodel 结果里按列名取值；命名有出入时退化为按两个字段名模糊匹配
pull_column <- function(frame, name, first, second) {
  if (name %in% names(frame)) return(as.numeric(frame[[name]]))
  hit <- grep(paste0(".*", first, ".*", second, "|.*", second, ".*", first),
              names(frame), value = TRUE)
  hit <- hit[!grepl("Spearman|Cov_", hit)]
  if (length(hit)) return(as.numeric(frame[[hit[1]]]))
  NULL
}

as_plain_df <- function(x) {
  if (inherits(x, "sf")) st_drop_geometry(x) else as.data.frame(x)
}

compute <- function() {
  pop <- st_read(SHP_PATH, quiet = TRUE)
  cols <- names(pop)

  resolve_field <- function(var) {
    if (var %in% cols) return(var)
    alt <- make.names(var)
    if (alt %in% cols) return(alt)
    stop(sprintf("字段「%s」不存在，可用字段: %s", var, paste(cols, collapse = ", ")))
  }
  vars_r <- vapply(vars, resolve_field, character(1), USE.NAMES = FALSE)
  # 两种写法（如 DBF 里的 2024_pop 与 sf 读出的 X2024_pop）可能解析到同一列，
  # 按解析后的真实列名去重，否则同一个字段会被当成两个参与配对
  keep <- !duplicated(vars_r)
  if (!all(keep)) {
    vars <- vars[keep]
    vars_r <- vars_r[keep]
  }
  if (length(vars_r) < 2) stop("去重后参与分析的字段不足两个")

  # 与主算法一致：全部参与字段都非空才纳入，所有配对共用同一份样本
  attr_df <- st_drop_geometry(pop)[, vars_r, drop = FALSE]
  valid <- complete.cases(attr_df)
  n0 <- nrow(pop)
  if (sum(valid) < 2) stop("清洗缺失值后有效样本不足，无法计算")

  pop_valid <- st_transform(pop[valid, ], PROJ_CRS)
  pop_valid_sp <- as(pop_valid, "Spatial")

  nvar <- length(vars_r)
  # 与 gwr_attribute.R 同一套配对口径：对外用客户端传入的字段名（y_name/x_name），
  # 只有 R 内部的计算才用 sf 改写后的真实列名（y/x）
  pairs <- list()
  for (i in seq_len(nvar - 1L)) {
    for (j in (i + 1L):nvar) {
      pairs[[length(pairs) + 1L]] <- list(
        y = vars_r[i], x = vars_r[j],
        y_name = vars[i], x_name = vars[j],
        key = paste0(safe_tag(vars[i]), "__vs__", safe_tag(vars[j])),
        label = paste(vars[i], "~", vars[j])
      )
    }
  }
  n_pair <- length(pairs)
  n_bw <- length(bandwidths)
  n_valid <- sum(valid)

  # 空序列占位：某个带宽算不出来时该档整体填 NA，不中断其它档
  na_series <- function() replicate(n_bw, rep(NA_real_, n0), simplify = FALSE)

  # series[[指标]][[配对序号]][[带宽序号]] = 逐要素向量（已对齐回原始要素顺序）
  series <- lapply(
    setNames(vector("list", 9L),
             c("local_r2", "coefficient", "local_corr", "lme", "lmae",
               "lmre", "lrmse", "residual", "stud_residual")),
    function(...) replicate(n_pair, na_series(), simplify = FALSE)
  )
  curves <- replicate(n_pair, vector("list", n_bw), simplify = FALSE)

  # 把一条带宽 / 一个配对的有效值写回序列，被剔除的要素保持 NA
  put_series <- function(metric, pair_index, bw_index, values) {
    cell <- series[[metric]][[pair_index]][[bw_index]]
    cell[valid] <- values
    series[[metric]][[pair_index]][[bw_index]] <<- cell
  }

  for (bw_index in seq_len(n_bw)) {
    bw <- bandwidths[[bw_index]]

    for (pair_index in seq_len(n_pair)) {
      pair <- pairs[[pair_index]]
      fml <- as.formula(paste(pair$y, "~", pair$x))
      gr <- tryCatch(
        gwr.basic(fml, pop_valid, bw = bw, adaptive = ADAPTIVE, kernel = KERNEL),
        error = function(e) NULL
      )
      if (is.null(gr)) {
        curves[[pair_index]][[bw_index]] <- list(
          bandwidth = as.integer(bw), aicc = NA, r2 = NA,
          local_r2_median = NA, coefficient_median = NA,
          residual_rmse = NA, stud_residual_median = NA
        )
        next
      }
      lr2_valid   <- as.numeric(gr$SDF$Local_R2)
      coef_valid  <- as.numeric(gr$SDF[[pair$x]])
      resid_valid <- as.numeric(gr$SDF$residual)
      stud_valid  <- as.numeric(gr$SDF$Stud_residual)

      put_series("local_r2", pair_index, bw_index, lr2_valid)
      put_series("coefficient", pair_index, bw_index, coef_valid)
      put_series("residual", pair_index, bw_index, resid_valid)
      put_series("stud_residual", pair_index, bw_index, stud_valid)

      diag <- gr$GW.diagnostic
      curves[[pair_index]][[bw_index]] <- list(
        bandwidth = as.integer(bw),
        aicc = json_number(diag$AICc),
        r2 = json_number(diag$gw.R2),
        local_r2_median = json_number(med(lr2_valid)),
        coefficient_median = json_number(med(coef_valid)),
        residual_rmse = json_number(safe_rmse(resid_valid)),
        stud_residual_median = json_number(med(stud_valid))
      )
    }

    # gwss / gwmv 与配对无关：一次传全部字段即可拿到 C(N,2) 对的结果，
    # 权重只在每个样本点上算一次，所以每档带宽只需各调用一次。
    # 字段逆序传入的理由见 gwr_attribute.R（让 LMRE 分母恒为自变量 X，
    # 且 LME 取负后即为约定的 Y - X）。
    order_vars <- rev(vars_r)
    extra <- tryCatch({
      gss <- gwss(pop_valid_sp, vars = order_vars, adaptive = ADAPTIVE, bw = bw, kernel = KERNEL)
      invisible(capture.output(
        gv <- gwmv(pop_valid, vars = order_vars, adaptive = ADAPTIVE, bw = bw, kernel = KERNEL)
      ))
      list(gss = as_plain_df(gss$SDF), gv = as_plain_df(gv$SDF))
    }, error = function(e) NULL)

    if (!is.null(extra)) {
      for (pair_index in seq_len(n_pair)) {
        pair <- pairs[[pair_index]]
        corr_v <- pull_column(extra$gss, gwss_col(pair$x, pair$y), pair$x, pair$y)
        lme_v  <- pull_column(extra$gv, gwmv_col("LME",   pair$x, pair$y), pair$x, pair$y)
        lmae_v <- pull_column(extra$gv, gwmv_col("LMAE",  pair$x, pair$y), pair$x, pair$y)
        lmre_v <- pull_column(extra$gv, gwmv_col("LMRE",  pair$x, pair$y), pair$x, pair$y)
        lrmse_v<- pull_column(extra$gv, gwmv_col("LRMSE", pair$x, pair$y), pair$x, pair$y)
        if (is.null(corr_v) || is.null(lme_v) || is.null(lmae_v) ||
            is.null(lmre_v) || is.null(lrmse_v)) next
        put_series("local_corr", pair_index, bw_index, corr_v)
        # 逆序传入 → Σw(X-Y)，取负还原成约定的 Σw(Y-X)；其余三个量本身对称
        put_series("lme", pair_index, bw_index, -lme_v)
        put_series("lmae", pair_index, bw_index, lmae_v)
        put_series("lmre", pair_index, bw_index, lmre_v)
        put_series("lrmse", pair_index, bw_index, lrmse_v)
      }
    }
  }

  names(series$local_r2) <- names(series$coefficient) <- vapply(pairs, function(p) p$key, character(1))
  for (name in setdiff(names(series), c("local_r2", "coefficient"))) {
    names(series[[name]]) <- names(series$local_r2)
  }
  names(curves) <- names(series$local_r2)

  list(pairs = pairs, curves = curves, series = series,
       n_features = n0, n_valid = n_valid, dropped = n0 - n_valid)
}

r <- tryCatch(compute(), error = function(e) e)
if (inherits(r, "error")) write_error(paste("算法执行失败:", conditionMessage(r)))

# by_pair：每个配对一套曲线与逐要素序列
by_pair <- list()
for (pair in r$pairs) {
  key <- pair$key
  by_pair[[key]] <- c(
    list(key = key, label = pair$label, y = pair$y_name, x = pair$x_name,
         curve = r$curves[[key]]),
    lapply(r$series, function(group) group[[key]])
  )
}

first_key <- r$pairs[[1]]$key
first <- by_pair[[first_key]]

result <- list(
  status  = "success",
  engine  = "R 属性 GWR · 带宽探索",
  message = sprintf("带宽探索完成：%s 共 %s 组配对，%s 个带宽，有效样本 %s，剔除缺失 %s 条。",
                    paste(vapply(r$pairs, function(p) p$label, character(1)), collapse = "、"),
                    length(r$pairs), length(bandwidths), r$n_valid, r$dropped),
  bandwidths = as.list(bandwidths),
  by_pair = by_pair,
  pairs = lapply(r$pairs, function(p) list(key = p$key, label = p$label,
                                           y = p$y_name, x = p$x_name)),
  # 第一组配对的平铺兼容字段
  curve = first$curve,
  local_r2 = first$local_r2,
  coefficient = first$coefficient,
  local_corr = first$local_corr,
  lme = first$lme,
  lmae = first$lmae,
  lmre = first$lmre,
  lrmse = first$lrmse,
  residual = first$residual,
  stud_residual = first$stud_residual,
  n_features = r$n_features,
  dropped = r$dropped,
  config = config
)

jsonlite::write_json(result, output_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
