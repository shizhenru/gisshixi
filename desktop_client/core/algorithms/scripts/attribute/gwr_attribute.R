# ============================================================================
#  属性数据 · 地理加权回归(GWR)验证算法（桌面端适配器）
# ----------------------------------------------------------------------------
#  约定 : JSON 配置进 → JSON 结果出，供 core/algorithms/r_runner.py 调用。
#  调用 : Rscript gwr_attribute.R <config.json> <output.json>
#  输入 : 一个含 X / Y 两个数值字段的矢量数据(shapefile/GeoPackage/GeoJSON)
#  输出 : 全局指标(ME/MAE/MRE/RMSE/相关系数) + 逐要素局部指标
#         局部 R²/系数/局部相关系数/LME/LMAE/LMRE/LRMSE(按原始要素顺序对齐)
#  依赖 : jsonlite / sf / GWmodel / sp
#  说明 : 本脚本是对「属性数据算法/#testcommand.r」的参数化封装，
#         去掉硬编码字段重命名，改由 config 传入 X/Y 字段名，并输出 JSON 结果。
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
              metrics = list(), message = msg, local_values = list())
  jsonlite::write_json(res, output_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
  quit(save = "no", status = 0)
}

# 手动写最小 JSON，避免 jsonlite 缺失时无法上报错误
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  cat('{\n  "status": "error",\n  "engine": "R 属性 GWR",\n  "message": "请先安装 R 包 jsonlite",\n  "metrics": {},\n  "local_values": []\n}\n',
      file = output_path)
  quit(save = "no", status = 0)
}
for (pkg in c("sf", "GWmodel", "sp")) {
  if (!requireNamespace(pkg, quietly = TRUE)) write_error(sprintf("请先安装 R 包 %s", pkg))
}

config <- jsonlite::fromJSON(config_path, simplifyVector = FALSE)

SHP_PATH <- config$shp_path %||% config$data_path
xvar <- config$independent_variable %||% config$x
yvar <- config$dependent_variable %||% config$y
if (is.null(SHP_PATH) || !nzchar(SHP_PATH)) write_error("缺少输入矢量路径(shp_path)")
if (is.null(xvar) || !nzchar(xvar)) write_error("缺少自变量 X(independent_variable)")
if (is.null(yvar) || !nzchar(yvar)) write_error("缺少因变量 Y(dependent_variable)")

# 中文界面参数 → R 参数
KERNEL <- switch(config$kernel %||% "双平方核",
  "双平方核" = "bisquare", "高斯核" = "gaussian", "指数核" = "exponential",
  "bisquare" = "bisquare", "gaussian" = "gaussian", "exponential" = "exponential",
  "bisquare")
ADAPTIVE <- identical(config$bandwidth_mode %||% "自适应带宽", "自适应带宽")
AUTO_BW  <- isTRUE(config$auto_bandwidth)
BW       <- suppressWarnings(as.numeric(config$bandwidth %||% "25"))
if (is.na(BW) || BW <= 0) BW <- 25
PROJ_CRS <- config$crs %||%
  "+proj=aea +lat_1=25 +lat_2=47 +lat_0=0 +lon_0=105 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"

WRITE_SHP <- isTRUE(config$write_shp)
OUT_DIR <- config$output_dir %||% file.path(dirname(output_path), "attribute_results")

suppressPackageStartupMessages({ library(sf); library(GWmodel); library(sp) })
sf_use_s2(FALSE)

# 定位脚本所在目录，使 source("gwmv.r") 不依赖工作目录
SCRIPT_DIR <- (function() {
  a <- commandArgs(trailingOnly = FALSE)
  f <- sub("^--file=", "", a[grepl("^--file=", a)])
  if (length(f)) dirname(normalizePath(f[1])) else getwd()
})()
source(file.path(SCRIPT_DIR, "gwmv.r"))

# 全局统计量(约定: 误差 = Y - X)
global_stats <- function(y, x) {
  d <- y - x
  mre <- if (any(x == 0)) mean(abs(d[x != 0]) / x[x != 0]) else mean(abs(d) / x)
  c(ME = mean(d), MAE = mean(abs(d)), MRE = mre,
    RMSE = sqrt(mean(d^2)), Corr = cor(y, x))
}

med <- function(v) {
  v <- v[is.finite(v)]
  if (!length(v)) NA else median(v)
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
  xvar_r <- resolve_field(xvar)
  yvar_r <- resolve_field(yvar)

  attr_df <- st_drop_geometry(pop)[, c(xvar_r, yvar_r), drop = FALSE]
  valid <- complete.cases(attr_df)
  n0 <- nrow(pop)
  dropped <- n0 - sum(valid)
  pop_valid <- pop[valid, ]
  if (nrow(pop_valid) < 2) stop("清洗缺失值后有效样本不足，无法计算")

  pop_valid <- st_transform(pop_valid, PROJ_CRS)
  pop_valid_sp <- as(pop_valid, "Spatial")

  gs <- global_stats(pop_valid[[yvar_r]], pop_valid[[xvar_r]])
  fml <- as.formula(paste(yvar_r, "~", xvar_r))

  if (AUTO_BW) {
    invisible(capture.output(bw <- bw.gwr(fml, pop_valid, approach = "AIC", adaptive = ADAPTIVE, kernel = KERNEL)))
  } else {
    bw <- BW
  }

  gss <- gwss(pop_valid_sp, vars = c(yvar_r, xvar_r), adaptive = ADAPTIVE, bw = bw, kernel = KERNEL)
  corr_col <- grep("Corr", names(gss$SDF), value = TRUE)[1]

  invisible(capture.output(gv <- gwmv(pop_valid, vars = c(yvar_r, xvar_r), adaptive = ADAPTIVE, bw = bw, kernel = KERNEL)))
  lv <- st_drop_geometry(gv$SDF)

  gr <- gwr.basic(fml, pop_valid, bw = bw, adaptive = ADAPTIVE, kernel = KERNEL)

  # 有效行的局部值
  local_r2_v <- as.numeric(gr$SDF$Local_R2)
  coef_v     <- as.numeric(gr$SDF[[xvar_r]])
  corr_v     <- as.numeric(gss$SDF[[corr_col]])
  lme_v      <- as.numeric(lv[[paste0("LME_",   yvar_r, "_", xvar_r)]])
  lmae_v     <- as.numeric(lv[[paste0("LMAE_",  yvar_r, "_", xvar_r)]])
  lmre_v     <- as.numeric(lv[[paste0("LMRE_",  yvar_r, "_", xvar_r)]])
  lrmse_v    <- as.numeric(lv[[paste0("LRMSE_", yvar_r, "_", xvar_r)]])

  # 对齐回原始要素顺序（被剔除的填 NA）
  align <- function(v) { out <- rep(NA_real_, n0); out[valid] <- v; out }

  list(
    gs = gs, bw = bw, dropped = dropped, n_valid = nrow(pop_valid),
    pop = pop,  # 原始（未投影）要素，用于写出结果 SHP
    local_r2 = align(local_r2_v), coefficient = align(coef_v),
    local_corr = align(corr_v), lme = align(lme_v), lmae = align(lmae_v),
    lmre = align(lmre_v), lrmse = align(lrmse_v)
  )
}

r <- tryCatch(compute(), error = function(e) e)
if (inherits(r, "error")) write_error(paste("算法执行失败:", conditionMessage(r)))

metrics <- list(
  me          = sprintf("%.4f", r$gs[["ME"]]),
  mae         = sprintf("%.4f", r$gs[["MAE"]]),
  mre         = sprintf("%.4f", r$gs[["MRE"]]),
  rmse        = sprintf("%.4f", r$gs[["RMSE"]]),
  correlation = sprintf("%.4f", r$gs[["Corr"]]),
  local_r2_median    = sprintf("%.4f", med(r$local_r2)),
  coefficient_median = sprintf("%.4f", med(r$coefficient)),
  local_corr_median  = sprintf("%.4f", med(r$local_corr)),
  lme_median         = sprintf("%.4f", med(r$lme)),
  lmae_median        = sprintf("%.4f", med(r$lmae)),
  lmre_median        = sprintf("%.4f", med(r$lmre)),
  lrmse_median       = sprintf("%.4f", med(r$lrmse)),
  bandwidth          = as.character(r$bw),
  samples            = as.character(r$n_valid),
  dropped            = as.character(r$dropped)
)

# 写出结果 SHP（原始几何 + 附加结果列）
output_shp <- ""
if (WRITE_SHP) {
  dir.create(OUT_DIR, recursive = TRUE, showWarnings = FALSE)
  tag <- paste0(yvar, "_vs_", xvar)
  shp_target <- file.path(OUT_DIR, paste0("gwr_", tag, ".shp"))
  out <- r$pop
  out$Local_R2 <- r$local_r2
  out$Coeff    <- r$coefficient
  out$Corr     <- r$local_corr
  out$LME      <- r$lme
  out$LMAE     <- r$lmae
  out$LMRE     <- r$lmre
  out$LRMSE    <- r$lrmse
  ok <- tryCatch({
    st_write(out, shp_target, append = FALSE, quiet = TRUE, layer_options = "ENCODING=UTF-8")
    TRUE
  }, error = function(e) FALSE)
  if (ok) output_shp <- shp_target
}

columns <- list(
  local_r2   = round(r$local_r2, 6),
  coefficient = round(r$coefficient, 6),
  local_corr = round(r$local_corr, 6),
  lme        = round(r$lme, 6),
  lmae       = round(r$lmae, 6),
  lmre       = round(r$lmre, 6),
  lrmse      = round(r$lrmse, 6)
)

local_values <- r$local_r2
local_values[!is.finite(local_values)] <- NA
local_values <- as.numeric(round(local_values, 4))
local_values <- local_values[!is.na(local_values)]

result <- list(
  status  = "success",
  engine  = "R 属性 GWR",
  metrics = metrics,
  message = sprintf("属性 GWR 完成：%s ~ %s，有效样本 %s，带宽 %s(%s)，剔除缺失 %s 条。",
                    yvar, xvar, metrics$samples, metrics$bandwidth,
                    if (ADAPTIVE) "近邻数" else "米", metrics$dropped),
  local_values = local_values,
  columns = columns,
  output_shp = output_shp,
  config = config
)

jsonlite::write_json(result, output_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
