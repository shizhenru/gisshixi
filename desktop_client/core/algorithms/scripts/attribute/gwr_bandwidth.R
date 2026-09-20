# ============================================================================
#  属性数据 · GWR 带宽区间探索（桌面端适配器）
# ----------------------------------------------------------------------------
#  约定 : JSON 配置进 → JSON 结果出，供 core/algorithms/r_runner.py 调用。
#  调用 : Rscript gwr_bandwidth.R <config.json> <output.json>
#  输入 : 一个含 X / Y 两个数值字段的矢量数据(shapefile/GeoPackage/GeoJSON)
#  输出 : 在给定带宽序列(默认 100~1000 步长 100，最近邻个数)上依次运行
#         gwr.basic，返回每条带宽的指标曲线点，以及逐要素局部 R² / 系数
#         (按原始要素顺序对齐，被剔除的填 NA)，供客户端绘制带宽曲线与局部地图。
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
              bandwidths = list(), local_r2 = list(), coefficient = list(),
              residual = list(), stud_residual = list())
  jsonlite::write_json(res, output_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
  quit(save = "no", status = 0)
}

if (!requireNamespace("jsonlite", quietly = TRUE)) {
  cat('{\n  "status": "error",\n  "engine": "R 属性 GWR · 带宽探索",\n  "message": "请先安装 R 包 jsonlite",\n  "curve": [],\n  "bandwidths": [],\n  "local_r2": [],\n  "coefficient": [],\n  "residual": [],\n  "stud_residual": []\n}\n',
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

compute <- function() {
  pop <- st_read(SHP_PATH, quiet = TRUE)
  cols <- names(pop)

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
  if (sum(valid) < 2) stop("清洗缺失值后有效样本不足，无法计算")

  pop_valid <- st_transform(pop[valid, ], PROJ_CRS)
  pop_valid_sp <- as(pop_valid, "Spatial")
  fml <- as.formula(paste(yvar_r, "~", xvar_r))

  curve <- list()
  local_r2_list <- list()
  coefficient_list <- list()
  local_corr_list <- list()
  lme_list <- list()
  lmae_list <- list()
  lmre_list <- list()
  lrmse_list <- list()
  residual_list <- list()
  stud_residual_list <- list()

  for (bw in bandwidths) {
    gr <- tryCatch(
      gwr.basic(fml, pop_valid, bw = bw, adaptive = ADAPTIVE, kernel = KERNEL),
      error = function(e) NULL
    )
    if (is.null(gr)) {
      # 该带宽无法计算（如最近邻数过小/过大），结果填 NA，不中断整体
      curve[[length(curve) + 1L]] <- list(
        bandwidth = as.integer(bw),
        aicc = NA, r2 = NA,
        local_r2_median = NA, coefficient_median = NA,
        residual_rmse = NA, stud_residual_median = NA
      )
      local_r2_list[[length(local_r2_list) + 1L]] <- rep(NA_real_, n0)
      coefficient_list[[length(coefficient_list) + 1L]] <- rep(NA_real_, n0)
      local_corr_list[[length(local_corr_list) + 1L]] <- rep(NA_real_, n0)
      lme_list[[length(lme_list) + 1L]] <- rep(NA_real_, n0)
      lmae_list[[length(lmae_list) + 1L]] <- rep(NA_real_, n0)
      lmre_list[[length(lmre_list) + 1L]] <- rep(NA_real_, n0)
      lrmse_list[[length(lrmse_list) + 1L]] <- rep(NA_real_, n0)
      residual_list[[length(residual_list) + 1L]] <- rep(NA_real_, n0)
      stud_residual_list[[length(stud_residual_list) + 1L]] <- rep(NA_real_, n0)
      next
    }
    lr2_valid <- as.numeric(gr$SDF$Local_R2)
    coef_valid <- as.numeric(gr$SDF[[xvar_r]])
    resid_valid <- as.numeric(gr$SDF$residual)
    stud_valid <- as.numeric(gr$SDF$Stud_residual)
    diag <- gr$GW.diagnostic

    # 局部相关系数 + 局部验证指标（与 gwr_attribute.R 写出的结果字段对齐；
    # 若计算失败仅这些字段填 NA，不影响 local_r2 等）
    corr_valid <- rep(NA_real_, sum(valid))
    lme_valid <- rep(NA_real_, sum(valid))
    lmae_valid <- rep(NA_real_, sum(valid))
    lmre_valid <- rep(NA_real_, sum(valid))
    lrmse_valid <- rep(NA_real_, sum(valid))
    extra <- tryCatch({
      gss <- gwss(pop_valid_sp, vars = c(yvar_r, xvar_r), adaptive = ADAPTIVE, bw = bw, kernel = KERNEL)
      corr_col <- grep("Corr", names(gss$SDF), value = TRUE)[1]
      gv <- gwmv(pop_valid, vars = c(yvar_r, xvar_r), adaptive = ADAPTIVE, bw = bw, kernel = KERNEL)
      lv <- st_drop_geometry(gv$SDF)
      list(
        corr = as.numeric(gss$SDF[[corr_col]]),
        lme  = as.numeric(lv[[paste0("LME_",   yvar_r, "_", xvar_r)]]),
        lmae = as.numeric(lv[[paste0("LMAE_",  yvar_r, "_", xvar_r)]]),
        lmre = as.numeric(lv[[paste0("LMRE_",  yvar_r, "_", xvar_r)]]),
        lrmse = as.numeric(lv[[paste0("LRMSE_", yvar_r, "_", xvar_r)]])
      )
    }, error = function(e) NULL)
    if (!is.null(extra)) {
      corr_valid <- extra$corr
      lme_valid <- extra$lme
      lmae_valid <- extra$lmae
      lmre_valid <- extra$lmre
      lrmse_valid <- extra$lrmse
    }

    # 对齐回原始要素顺序（被剔除的填 NA）
    lr2 <- rep(NA_real_, n0); lr2[valid] <- lr2_valid
    coef <- rep(NA_real_, n0); coef[valid] <- coef_valid
    corr <- rep(NA_real_, n0); corr[valid] <- corr_valid
    lme  <- rep(NA_real_, n0); lme[valid] <- lme_valid
    lmae <- rep(NA_real_, n0); lmae[valid] <- lmae_valid
    lmre <- rep(NA_real_, n0); lmre[valid] <- lmre_valid
    lrmse <- rep(NA_real_, n0); lrmse[valid] <- lrmse_valid
    resid <- rep(NA_real_, n0); resid[valid] <- resid_valid
    stud <- rep(NA_real_, n0); stud[valid] <- stud_valid

    curve[[length(curve) + 1L]] <- list(
      bandwidth = as.integer(bw),
      aicc = json_number(diag$AICc),
      r2 = json_number(diag$gw.R2),
      local_r2_median = json_number(med(lr2_valid)),
      coefficient_median = json_number(med(coef_valid)),
      residual_rmse = json_number(safe_rmse(resid_valid)),
      stud_residual_median = json_number(med(stud_valid))
    )
    local_r2_list[[length(local_r2_list) + 1L]] <- lr2
    coefficient_list[[length(coefficient_list) + 1L]] <- coef
    local_corr_list[[length(local_corr_list) + 1L]] <- corr
    lme_list[[length(lme_list) + 1L]] <- lme
    lmae_list[[length(lmae_list) + 1L]] <- lmae
    lmre_list[[length(lmre_list) + 1L]] <- lmre
    lrmse_list[[length(lrmse_list) + 1L]] <- lrmse
    residual_list[[length(residual_list) + 1L]] <- resid
    stud_residual_list[[length(stud_residual_list) + 1L]] <- stud
  }

  list(
    curve = curve,
    bandwidths = as.list(bandwidths),
    local_r2 = local_r2_list,
    coefficient = coefficient_list,
    local_corr = local_corr_list,
    lme = lme_list,
    lmae = lmae_list,
    lmre = lmre_list,
    lrmse = lrmse_list,
    residual = residual_list,
    stud_residual = stud_residual_list,
    n_features = n0,
    dropped = n0 - sum(valid)
  )
}

r <- tryCatch(compute(), error = function(e) e)
if (inherits(r, "error")) write_error(paste("算法执行失败:", conditionMessage(r)))

result <- list(
  status  = "success",
  engine  = "R 属性 GWR · 带宽探索",
  message = sprintf("带宽探索完成：%s ~ %s，共 %s 个带宽，有效样本 %s，剔除缺失 %s 条。",
                    yvar, xvar, length(r$bandwidths), r$n_features - r$dropped, r$dropped),
  curve = r$curve,
  bandwidths = r$bandwidths,
  local_r2 = r$local_r2,
  coefficient = r$coefficient,
  local_corr = r$local_corr,
  lme = r$lme,
  lmae = r$lmae,
  lmre = r$lmre,
  lrmse = r$lrmse,
  residual = r$residual,
  stud_residual = r$stud_residual,
  n_features = r$n_features,
  dropped = r$dropped,
  config = config
)

jsonlite::write_json(result, output_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
