# ============================================================================
#  属性数据 · 地理加权回归(GWR)验证算法（桌面端适配器）
# ----------------------------------------------------------------------------
#  约定 : JSON 配置进 → JSON 结果出，供 core/algorithms/r_runner.py 调用。
#  调用 : Rscript gwr_attribute.R <config.json> <output.json>
#  输入 : 一个含 N(≥2) 个数值字段的矢量数据(shapefile/GeoPackage/GeoJSON)
#         config$variables = ["字段A","字段B","字段C"] → 两两配对共 C(N,2) 组
#         约定：候选列表里靠前的字段作因变量 Y，靠后的作自变量 X（回归 Y ~ X）
#  输出 : 每组配对的 全局指标(ME/MAE/MRE/RMSE/相关系数) + 逐要素局部指标
#         (局部 R²/系数/局部相关系数/LME/LMAE/LMRE/LRMSE，按原始要素顺序对齐)
#         多组结果走 *_by_pair 系列字段；第一组同时以旧字段名(metrics/columns/
#         output_shp/figures)再发一份，保证既有调用方不炸。
#  依赖 : jsonlite / sf / GWmodel / sp
#  说明 : 本脚本是对「属性数据算法/#testcommand.r」的参数化封装。该参考脚本
#         原本就是多对(PAIRS)分析，这里恢复其多对能力并去掉硬编码字段重命名。
# ============================================================================

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2) stop("需要 config.json 和 output.json 两个参数")
config_path <- args[[1]]
output_path <- args[[2]]

# 空值兜底
`%||%` <- function(a, b) if (is.null(a) || length(a) == 0L || (length(a) == 1L && is.na(a))) b else a

# 统一写错误 JSON，保证桌面端能读到可读的失败原因而非子进程崩溃
write_error <- function(msg) {
  res <- list(status = "error", engine = "R 属性 GWR",
              metrics = list(), message = msg, local_values = list(),
              pairs = list(), metrics_by_pair = list(), shp_by_pair = list(),
              pairwise_metrics = list(), local_statistics = list(),
              figures = list(), figures_by_pair = list())
  jsonlite::write_json(res, output_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
  quit(save = "no", status = 0)
}

# 手动写最小 JSON，避免 jsonlite 缺失时无法上报错误
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  cat('{\n  "status": "error",\n  "engine": "R 属性 GWR",\n  "message": "请先安装 R 包 jsonlite",\n  "metrics": {},\n  "local_values": [],\n  "pairs": []\n}\n',
      file = output_path)
  quit(save = "no", status = 0)
}
for (pkg in c("sf", "GWmodel", "sp")) {
  if (!requireNamespace(pkg, quietly = TRUE)) write_error(sprintf("请先安装 R 包 %s", pkg))
}
# ggplot2 只用于出图，缺失时跳过图、分析结果照常返回
HAS_GGPLOT <- requireNamespace("ggplot2", quietly = TRUE)
if (HAS_GGPLOT) suppressPackageStartupMessages(library(ggplot2))

config <- jsonlite::fromJSON(config_path, simplifyVector = FALSE)

SHP_PATH <- config$shp_path %||% config$data_path

# 候选字段：优先读 variables 列表；旧的 dependent_variable / independent_variable
# 两个标量继续兼容（按「因变量在前、自变量在后」还原成同一套配对口径）。
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
if (length(vars) < 2) {
  write_error("至少需要选择两个参与分析的字段(variables)")
}

if (is.null(SHP_PATH) || !nzchar(SHP_PATH)) write_error("缺少输入矢量路径(shp_path)")

# 中文界面参数 → R 参数
KERNEL <- switch(config$kernel %||% "双平方核",
  "双平方核" = "bisquare", "高斯核" = "gaussian", "指数核" = "exponential",
  "bisquare" = "bisquare", "gaussian" = "gaussian", "exponential" = "exponential",
  "bisquare")
ADAPTIVE <- identical(config$bandwidth_mode %||% "最近邻个数", "最近邻个数")
AUTO_BW  <- isTRUE(config$auto_bandwidth)
BW       <- suppressWarnings(as.numeric(config$bandwidth %||% "25"))
if (is.na(BW) || BW <= 0) BW <- 25
PROJ_CRS <- config$crs %||%
  "+proj=aea +lat_1=25 +lat_2=47 +lat_0=0 +lon_0=105 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"

WRITE_SHP <- isTRUE(config$write_shp)
OUT_DIR <- config$output_dir %||% file.path(dirname(output_path), "attribute_results")
# 立刻建目录：出图发生在 compute() 内部，早于下面写 SHP 的 dir.create
dir.create(OUT_DIR, recursive = TRUE, showWarnings = FALSE)

suppressPackageStartupMessages({ library(sf); library(GWmodel); library(sp) })
sf_use_s2(FALSE)

# 定位脚本所在目录，使 source("gwmv.r") 不依赖工作目录
SCRIPT_DIR <- (function() {
  a <- commandArgs(trailingOnly = FALSE)
  f <- sub("^--file=", "", a[grepl("^--file=", a)])
  if (length(f)) dirname(normalizePath(f[1])) else getwd()
})()
source(file.path(SCRIPT_DIR, "gwmv.r"))

# 全局统计量(约定: 误差 = Y - X，相对误差分母取 X)
global_stats <- function(y, x) {
  d <- y - x
  mre <- if (any(x == 0)) mean(abs(d[x != 0]) / x[x != 0]) else mean(abs(d) / x)
  c(ME = mean(d), MAE = mean(abs(d)), MRE = mre,
    RMSE = sqrt(mean(d^2)), Corr = cor(y, x))
}

# 全局诊断量格式化：GWmodel 不同版本字段可能缺失，缺失时给 NA 而不是让整段失败
fmt_diag <- function(value, digits = 4) {
  if (is.null(value) || length(value) == 0 || !is.finite(as.numeric(value)[1])) return(NA_character_)
  sprintf(paste0("%.", digits, "f"), as.numeric(value)[1])
}

med <- function(v) {
  v <- v[is.finite(v)]
  if (!length(v)) NA else median(v)
}

# 单个配对的局部指标统计量（结果页「局部统计摘要」表格要用）
safe_statistics <- function(v) {
  v <- v[is.finite(v)]
  if (!length(v)) {
    return(list(count = 0L, min = NA_real_, q1 = NA_real_, median = NA_real_,
                q3 = NA_real_, max = NA_real_, mean = NA_real_, sd = NA_real_))
  }
  qs <- as.numeric(stats::quantile(v, c(0.25, 0.75), names = FALSE))
  list(count = length(v), min = min(v), q1 = qs[1], median = median(v),
       q3 = qs[2], max = max(v), mean = mean(v), sd = stats::sd(v))
}

# 字段名 → 文件名 / 配对键用的安全标签
safe_tag <- function(value) {
  value <- gsub("[^A-Za-z0-9_.-]+", "_", value)
  value <- gsub("^_+|_+$", "", value)
  if (nzchar(value)) value else "field"
}

# GWmodel 的列名约定：gwmv 用下划线连接，gwss 用点号连接。
# 两者都不接受自定义分隔符，所以这里按同名规则拼出目标列名。
gwmv_col <- function(prefix, first, second) paste0(prefix, "_", first, "_", second)
gwss_col <- function(first, second) paste0("Corr_", first, ".", second)

# 从 GWmodel 结果里按列名取值。列名是拼出来的，若 GWmodel 版本换了分隔符
# 就退化为「同时含两个字段名」的模糊匹配，避免整段计算因命名差异直接失败。
pull_column <- function(frame, name, what, pair_label, first, second) {
  if (!name %in% names(frame)) {
    hit <- grep(paste0(".*", first, ".*", second, "|.*", second, ".*", first),
                names(frame), value = TRUE)
    hit <- hit[!grepl("Spearman|Cov_", hit)]
    if (length(hit)) return(as.numeric(frame[[hit[1]]]))
    stop(sprintf("计算 %s 失败：GWmodel 结果中找不到列「%s」或与之对应的配对列（配对 %s）",
                 what, name, pair_label))
  }
  as.numeric(frame[[name]])
}

# GWmodel 返回的 SDF 在 sp 输入下是 Spatial*DataFrame、sf 输入下是 sf，
# 两种都要能取成普通 data.frame 再按列名索引。
as_plain_df <- function(x) {
  if (inherits(x, "sf")) st_drop_geometry(x) else as.data.frame(x)
}

# ---------------------------------------------------------------------------
# 出图：与「属性数据算法/#testcommand.r」的五张图保持同一口径
#   （散点图由客户端 Python 侧渲染，这里不重复出）
#   多配对时每个配对一套图，文件名带配对标签，避免相互覆盖。
# ---------------------------------------------------------------------------
FIG_W <- 8
FIG_H <- 6
FIG_DPI <- 150

save_fig <- function(plot, path) {
  dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
  if (file.exists(path)) try(unlink(path), silent = TRUE)  # 先删旧图，避免文件被占用
  tryCatch({
    ggsave(path, plot = plot, width = FIG_W, height = FIG_H, dpi = FIG_DPI)
    TRUE
  }, error = function(e) FALSE)
}

# 误差直方图：黑虚线 = 0（无误差），红线 = 平均误差；整体偏左说明 X 系统性高于 Y
fig_error_hist <- function(x, y, label) {
  err <- y - x
  ggplot(data.frame(err = err), aes(x = err)) +
    geom_histogram(bins = 40, fill = "steelblue", colour = "white", alpha = 0.85) +
    geom_vline(xintercept = 0, linetype = "dashed", colour = "grey40") +
    geom_vline(xintercept = mean(err), colour = "red3", linewidth = 0.9) +
    labs(x = "Error: Y - X", y = "Frequency",
         title = sprintf("Error distribution: %s | mean = %.4g", label, mean(err))) +
    theme_bw()
}

# 局部 R² 直方图：越靠右拟合越好，分布越宽空间异质性越强
fig_r2_hist <- function(values, label) {
  ggplot(data.frame(v = values), aes(x = v)) +
    geom_histogram(bins = 40, fill = "darkorange", colour = "white", alpha = 0.85) +
    labs(x = "Local R-squared", y = "Frequency",
         title = paste("Local R2 distribution:", label)) +
    theme_bw()
}

# GWR 斜率系数直方图：红虚线 = 1（两数据一致时系数应为 1）
fig_coef_hist <- function(values, label) {
  ggplot(data.frame(v = values), aes(x = v)) +
    geom_histogram(bins = 40, fill = "forestgreen", colour = "white", alpha = 0.85) +
    geom_vline(xintercept = 1, linetype = "dashed", colour = "red3", linewidth = 0.9) +
    labs(x = "GWR slope coefficient", y = "Frequency",
         title = paste("GWR coefficient:", label, "| dashed line = 1")) +
    theme_bw()
}

# 专题图：Local_R2 单色渐变（越深拟合越好）、LME 发散色带（蓝负红正）
fig_map_r2 <- function(sf_data, label) {
  ggplot(sf_data) +
    geom_sf(aes(fill = Local_R2), colour = NA) +
    scale_fill_gradient(low = "#FEE391", high = "#662506", limits = c(0, 1), name = "Local R2") +
    labs(title = paste("Local R2 map:", label)) + theme_void()
}

fig_map_lme <- function(sf_data, label) {
  ggplot(sf_data) +
    geom_sf(aes(fill = LME), colour = NA) +
    scale_fill_gradient2(low = "#2166AC", mid = "#F7F7F7", high = "#B2182B",
                         midpoint = 0, name = "LME") +
    labs(title = paste("Local Mean Error map:", label)) + theme_void()
}

# 为一个配对生成五张图，返回 名称 -> 路径 的列表（失败/无 ggplot2 时返回空列表）
make_figures <- function(out_sf, x, y, r2_values, coef_values, pair_meta) {
  if (!HAS_GGPLOT) return(list())
  label <- pair_meta$label
  targets <- list(
    error_hist     = fig_error_hist(x, y, label),
    local_r2_hist  = fig_r2_hist(r2_values, label),
    coef_hist      = fig_coef_hist(coef_values, label),
    map_r2         = fig_map_r2(out_sf, label),
    map_lme        = fig_map_lme(out_sf, label)
  )
  paths <- list()
  for (name in names(targets)) {
    path <- file.path(OUT_DIR, paste0("fig_", pair_meta$tag, "_", name, ".png"))
    if (isTRUE(save_fig(targets[[name]], path))) paths[[name]] <- path
  }
  paths
}

# 主计算，任何异常都会转为可读错误
compute <- function() {
  pop <- st_read(SHP_PATH, quiet = TRUE)
  cols <- names(pop)

  # 字段名解析：R 会把以数字开头的字段自动加 X 前缀(如 2024_pop → X2024_pop)
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

  # 有效样本取「全部参与字段都非空」的交集：所有配对共用同一份样本，
  # 配对之间的指标才可直接比较（与 #testcommand.r 的 complete.cases 口径一致）。
  attr_df <- st_drop_geometry(pop)[, vars_r, drop = FALSE]
  valid <- complete.cases(attr_df)
  n0 <- nrow(pop)
  dropped <- n0 - sum(valid)
  pop_valid <- pop[valid, ]
  if (nrow(pop_valid) < 2) stop("清洗缺失值后有效样本不足，无法计算")

  pop_valid <- st_transform(pop_valid, PROJ_CRS)
  pop_valid_sp <- as(pop_valid, "Spatial")

  nvar <- length(vars_r)
  # 配对：候选列表里靠前的作因变量 Y、靠后的作自变量 X（回归 Y ~ X）。
  # 每对同时记住「计算用的真实列名」(y/x) 与「客户端传入的名字」(y_name/x_name)——
  # sf 读 shapefile 时会把 2024_pop 这类字段改写成 X2024_pop，若用改写过后的名字
  # 当配对键，客户端拿自己那套名字就再也对不上号（配对下拉切不动、结果 SHP 找不到）。
  # 所以对外一律用客户端传入的名字，只有 R 内部的计算才用真实列名。
  pairs <- list()
  for (i in seq_len(nvar - 1L)) {
    for (j in (i + 1L):nvar) {
      pairs[[length(pairs) + 1L]] <- list(
        y = vars_r[i], x = vars_r[j],
        y_name = vars[i], x_name = vars[j],
        key = paste0(safe_tag(vars[i]), "__vs__", safe_tag(vars[j])),
        tag = paste0(safe_tag(vars[i]), "_vs_", safe_tag(vars[j])),
        label = paste(vars[i], "~", vars[j])
      )
    }
  }

  # 带宽：所有配对共用同一个值，配对之间的差异才只来自数据本身。
  # 自动带宽只用第一组配对估计（GWmodel 的 bw.gwr 一次只能针对一条回归式），
  # 结果会随消息一并说明，避免用户误以为每组都各自调过。
  bw_source <- if (AUTO_BW) pairs[[1]]$label else NULL
  if (AUTO_BW) {
    fml1 <- as.formula(paste(pairs[[1]]$y, "~", pairs[[1]]$x))
    invisible(capture.output(
      bw <- bw.gwr(fml1, pop_valid, approach = "AIC", adaptive = ADAPTIVE, kernel = KERNEL)
    ))
  } else {
    bw <- BW
  }

  # gwss / gwmv 都按「一次传全部字段、内部两两配对」设计：
  # 权重只在每个样本点上算一次，配对数是内层的廉价向量运算。所以 N 个字段
  # 只调用一次就够，绝不能按配对循环调用（那会把权重计算乘上 C(N,2) 倍）。
  #
  # 字段顺序按倒序传入，是为了让两件事同时成立：
  #   1) gwmv 的相对误差分母恒为「后一个字段」= 自变量 X，与本脚本
  #      global_stats 的 MRE 定义(相对 X)、以及 #testcommand.r 的注释一致；
  #      正序传入时分母会是因变量 Y，两者对不上。
  #   2) 逆序后每对配对的 LME 列算出来是 Σw(X - Y)，取负即为约定的 Σw(Y - X)。
  order_vars <- rev(vars_r)

  gss <- gwss(pop_valid_sp, vars = order_vars, adaptive = ADAPTIVE, bw = bw, kernel = KERNEL)
  gss_df <- as_plain_df(gss$SDF)

  invisible(capture.output(
    gv <- gwmv(pop_valid, vars = order_vars, adaptive = ADAPTIVE, bw = bw, kernel = KERNEL)
  ))
  gv_df <- as_plain_df(gv$SDF)

  # 逆序传参下，原配对 (Y=vars_r[i], X=vars_r[j]) 对应 gwmv 列 LME_X_Y、
  # gwss 列 Corr_X.Y（相关系数对称，列名顺序不影响取值）。
  align <- function(v) { out <- rep(NA_real_, n0); out[valid] <- v; out }

  figures_by_pair <- list()
  metrics_by_pair <- list()
  shp_by_pair <- list()
  pairwise_metrics <- list()
  local_statistics <- list()
  first <- NULL

  for (pair in pairs) {
    yvar_r <- pair$y
    xvar_r <- pair$x
    fml <- as.formula(paste(yvar_r, "~", xvar_r))

    gr <- gwr.basic(fml, pop_valid, bw = bw, adaptive = ADAPTIVE, kernel = KERNEL)
    local_r2_v <- as.numeric(gr$SDF$Local_R2)
    coef_v     <- as.numeric(gr$SDF[[xvar_r]])
    corr_v     <- pull_column(gss_df, gwss_col(xvar_r, yvar_r), "局部相关系数",
                              pair$label, xvar_r, yvar_r)
    # 逆序传入 → LME 为 Σw(X-Y)，取负还原成约定的 Σw(Y-X)；其余三个量本身对称。
    lme_v      <- -pull_column(gv_df, gwmv_col("LME",   xvar_r, yvar_r), "局部平均误差",
                               pair$label, xvar_r, yvar_r)
    lmae_v     <- pull_column(gv_df, gwmv_col("LMAE",  xvar_r, yvar_r), "局部平均绝对误差",
                              pair$label, xvar_r, yvar_r)
    lmre_v     <- pull_column(gv_df, gwmv_col("LMRE",  xvar_r, yvar_r), "局部平均相对误差",
                              pair$label, xvar_r, yvar_r)
    lrmse_v    <- pull_column(gv_df, gwmv_col("LRMSE", xvar_r, yvar_r), "局部均方根误差",
                              pair$label, xvar_r, yvar_r)

    gs <- global_stats(pop_valid[[yvar_r]], pop_valid[[xvar_r]])

    columns <- list(
      local_r2   = align(local_r2_v),
      coefficient = align(coef_v),
      local_corr = align(corr_v),
      lme        = align(lme_v),
      lmae       = align(lmae_v),
      lmre       = align(lmre_v),
      lrmse      = align(lrmse_v)
    )

    # 专题图用的 sf：投影后的有效要素 + 局部指标列（列名与绘图层一致）
    fig_sf <- pop_valid
    fig_sf$Local_R2 <- local_r2_v
    fig_sf$Coeff    <- coef_v
    fig_sf$LME      <- lme_v
    figures <- tryCatch(
      make_figures(fig_sf, pop_valid[[xvar_r]], pop_valid[[yvar_r]],
                   local_r2_v, coef_v, pair),
      error = function(e) list()
    )

    # 写出该配对的结果 SHP（原始几何 + 结果列）。每个配对一个文件，
    # 列名沿用 Local_R2 / Coeff / ... 这类短名，避免 DBF 的 10 字符上限
    # 触发 sf 的 abbreviate() 把所有列名打乱。
    output_shp <- ""
    if (WRITE_SHP) {
      out <- pop
      out$Local_R2 <- columns$local_r2
      out$Coeff    <- columns$coefficient
      out$Corr     <- columns$local_corr
      out$LME      <- columns$lme
      out$LMAE     <- columns$lmae
      out$LMRE     <- columns$lmre
      out$LRMSE    <- columns$lrmse
      shp_target <- file.path(OUT_DIR, paste0("gwr_", pair$tag, ".shp"))
      ok <- tryCatch({
        st_write(out, shp_target, append = FALSE, quiet = TRUE, layer_options = "ENCODING=UTF-8")
        TRUE
      }, error = function(e) FALSE)
      if (ok) output_shp <- shp_target
    }

    metrics <- list(
      me          = sprintf("%.4f", gs[["ME"]]),
      mae         = sprintf("%.4f", gs[["MAE"]]),
      mre         = sprintf("%.4f", gs[["MRE"]]),
      rmse        = sprintf("%.4f", gs[["RMSE"]]),
      correlation = sprintf("%.4f", gs[["Corr"]]),
      r2          = fmt_diag(gr$GW.diagnostic$gw.R2),
      adj_r2      = fmt_diag(gr$GW.diagnostic$gwR2.adj),
      aicc        = fmt_diag(gr$GW.diagnostic$AICc, 1),
      local_r2_median    = sprintf("%.4f", med(local_r2_v)),
      coefficient_median = sprintf("%.4f", med(coef_v)),
      local_corr_median  = sprintf("%.4f", med(corr_v)),
      lme_median         = sprintf("%.4f", med(lme_v)),
      lmae_median        = sprintf("%.4f", med(lmae_v)),
      lmre_median        = sprintf("%.4f", med(lmre_v)),
      lrmse_median       = sprintf("%.4f", med(lrmse_v)),
      bandwidth          = as.character(bw),
      samples            = as.character(nrow(pop_valid)),
      dropped            = as.character(dropped)
    )

    pair_meta <- list(
      key = pair$key, label = pair$label, y = pair$y_name, x = pair$x_name,
      tag = pair$tag, output_shp = output_shp
    )
    # columns 不进 by_pair：每个配对 7 列 × 十几万要素，全量走 JSON 会让
    # 结果文件膨胀到几十 MB。其余配对的结果值由客户端直接从各自的 SHP 读。
    metrics_by_pair[[pair$key]] <- metrics
    if (nzchar(output_shp)) shp_by_pair[[pair$key]] <- output_shp
    figures_by_pair[[pair$key]] <- figures
    pairwise_metrics[[pair$key]] <- c(
      list(label = pair$label, y = pair$y_name, x = pair$x_name),
      metrics[setdiff(names(metrics), c("bandwidth", "samples", "dropped"))]
    )
    local_statistics[[pair$key]] <- list(
      local_r2   = safe_statistics(local_r2_v),
      coefficient = safe_statistics(coef_v),
      local_corr = safe_statistics(corr_v),
      lme        = safe_statistics(lme_v),
      lmae       = safe_statistics(lmae_v),
      lmre       = safe_statistics(lmre_v),
      lrmse      = safe_statistics(lrmse_v)
    )

    if (is.null(first)) {
      first <- list(pair = pair_meta, metrics = metrics, columns = columns,
                    figures = figures, local_r2 = columns$local_r2)
    }
  }

  list(
    pairs = lapply(pairs, function(p) list(key = p$key, label = p$label,
                                           y = p$y_name, x = p$x_name, tag = p$tag)),
    first = first,
    metrics_by_pair = metrics_by_pair,
    shp_by_pair = shp_by_pair,
    figures_by_pair = figures_by_pair,
    pairwise_metrics = pairwise_metrics,
    local_statistics = local_statistics,
    bw = bw,
    bw_source = bw_source,
    n_valid = nrow(pop_valid),
    dropped = dropped
  )
}

r <- tryCatch(compute(), error = function(e) e)
if (inherits(r, "error")) write_error(paste("算法执行失败:", conditionMessage(r)))

n_pairs <- length(r$pairs)
pair_labels <- vapply(r$pairs, function(p) p$label, character(1))
message_text <- sprintf(
  "属性 GWR 完成：%s 共 %s 组配对，有效样本 %s，带宽 %s(%s)，剔除缺失 %s 条。",
  paste(pair_labels, collapse = "、"), n_pairs, r$n_valid, r$bw,
  if (ADAPTIVE) "近邻数" else "米", r$dropped)
if (!is.null(r$bw_source)) {
  message_text <- paste0(message_text,
                         sprintf("（自动带宽由第一组 %s 估计，全部配对共用）", r$bw_source))
}

local_values <- r$first$local_r2
local_values[!is.finite(local_values)] <- NA
local_values <- as.numeric(round(local_values, 4))
local_values <- local_values[!is.na(local_values)]

result <- list(
  status  = "success",
  engine  = "R 属性 GWR",
  # 多配对结果
  pairs            = r$pairs,
  metrics_by_pair  = r$metrics_by_pair,
  shp_by_pair      = r$shp_by_pair,
  figures_by_pair  = r$figures_by_pair,
  pairwise_metrics = r$pairwise_metrics,
  local_statistics = r$local_statistics,
  # 第一组配对的兼容字段（旧调用方 / 结果页顶部的全局卡直接用这些）
  metrics      = r$first$metrics,
  local_values = local_values,
  columns      = lapply(r$first$columns, function(v) round(v, 6)),
  output_shp   = r$first$pair$output_shp,
  figures      = r$first$figures,
  message      = message_text,
  # 结果页要显示输出目录、并支持「打开结果目录」，必须显式带出来
  output_dir   = OUT_DIR,
  config       = config
)

jsonlite::write_json(result, output_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
