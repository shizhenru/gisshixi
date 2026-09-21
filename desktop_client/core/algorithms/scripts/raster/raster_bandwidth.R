# ============================================================================
#  栅格数据 · 窗口大小带宽区间探索（桌面端适配器）
# ----------------------------------------------------------------------------
#  约定 : JSON 配置进 → JSON 结果出，供 core/algorithms/r_runner.py 调用。
#  调用 : Rscript raster_bandwidth.R <config.json> <output.json>
#  输入 : 两个及以上单波段栅格（teradata / GeoTIFF）
#  输出 : 在给定窗口大小序列(奇数, 默认 3~99 步长 2)上依次计算局部指标，
#         返回每条窗口的指标曲线点、降采样局部 MAE 网格值（供图例分级）与
#         预览栅格路径（供地图拖动查看）。
#  说明 : 本脚本为带宽区间探索适配器，不修改原栅格算法
#         （../栅格数据算法/desktop_raster_terra_analysis.R），
#         仅复用其栅格对齐方式与指标公式；局部指标只计算第一组栅格对，
#         全部两两组合的全局指标只计算一次（与窗口大小无关）。
#  依赖 : jsonlite / terra
# ============================================================================

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2) stop("需要 config.json 和 output.json 两个参数")
config_path <- args[[1]]
output_path <- args[[2]]

# 空值兜底
`%||%` <- function(a, b) if (is.null(a) || length(a) == 0L) b else a

write_error <- function(msg) {
  res <- list(status = "error", engine = "R / terra · 带宽探索",
              message = msg, curve = list(), bandwidths = list(),
              local_mae = list(), previews = list(), pairwise_metrics = list())
  jsonlite::write_json(res, output_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
  quit(save = "no", status = 0)
}

for (pkg in c("jsonlite", "terra")) {
  if (!requireNamespace(pkg, quietly = TRUE)) write_error(sprintf("请先安装 R 包 %s", pkg))
}

config <- jsonlite::fromJSON(config_path, simplifyVector = FALSE)

raster_paths <- config$raster_paths %||% character()
raster_paths <- as.character(raster_paths[nzchar(raster_paths)])
if (length(raster_paths) < 2) write_error("栅格带宽探索至少需要两个栅格数据集")
if (any(!file.exists(raster_paths))) write_error("栅格输入文件不存在")

window_sizes <- suppressWarnings(as.integer(config$window_sizes %||% seq(3, 99, by = 2)))
window_sizes <- window_sizes[is.finite(window_sizes) & window_sizes >= 3 & window_sizes %% 2 == 1]
if (!length(window_sizes)) write_error("窗口大小序列为空或非法（需为 >= 3 的奇数）")

resampling <- config$resampling %||% "bilinear"
zero_epsilon <- as.numeric(config$zero_epsilon %||% 1e-12)
preview_dir <- config$preview_dir %||% file.path(dirname(output_path), "raster_previews")
preview_max_dim <- as.integer(config$preview_max_dim %||% 512L)
if (is.na(preview_max_dim) || preview_max_dim < 32) preview_max_dim <- 512L
legend_max_dim <- 96L  # 图例分级用的降采样网格边长（JSON 内数值网格）

dir.create(preview_dir, showWarnings = FALSE, recursive = TRUE)
dir.create(file.path(preview_dir, "temp"), showWarnings = FALSE, recursive = TRUE)
suppressPackageStartupMessages(library(terra))
# 临时文件统一落到预览目录（.runtime 下），避免占用用户系统临时目录
terraOptions(tempdir = file.path(preview_dir, "temp"))

safe_mean <- function(x, ...) {
  x <- x[is.finite(x)]
  if (!length(x)) return(NA_real_)
  mean(x)
}
safe_median <- function(x, ...) {
  x <- x[is.finite(x)]
  if (!length(x)) return(NA_real_)
  median(x)
}
safe_rmse <- function(x, ...) {
  x <- x[is.finite(x)]
  if (!length(x)) return(NA_real_)
  sqrt(mean(x^2))
}
safe_rms_from_squared <- function(x, ...) {
  x <- x[is.finite(x)]
  if (!length(x)) return(NA_real_)
  sqrt(mean(x))
}
safe_mre <- function(reference, comparison) {
  ok <- is.finite(reference) & is.finite(comparison) & abs(reference) > zero_epsilon
  if (!any(ok)) return(NA_real_)
  mean(abs((reference[ok] - comparison[ok]) / reference[ok]))
}
json_number <- function(value) {
  if (length(value) == 0 || !is.finite(value)) NA_real_ else value
}
safe_name <- function(value) {
  value <- gsub("[^A-Za-z0-9_-]+", "_", value)
  value <- gsub("^_+|_+$", "", value)
  if (!nzchar(value)) "raster" else value
}

input_names <- config$raster_names %||% tools::file_path_sans_ext(basename(raster_paths))
input_names <- as.character(input_names)
if (length(input_names) != length(raster_paths)) {
  input_names <- tools::file_path_sans_ext(basename(raster_paths))
}
input_names <- make.unique(vapply(input_names, safe_name, character(1)))

rasters <- lapply(raster_paths, terra::rast)
if (any(vapply(rasters, terra::nlyr, numeric(1)) != 1)) {
  write_error("每个栅格必须只包含一个波段")
}
reference_grid <- rasters[[1]]
aligned <- vector("list", length(rasters))
aligned[[1]] <- reference_grid
if (length(rasters) > 1) {
  for (index in 2:length(rasters)) {
    aligned[[index]] <- terra::project(rasters[[index]], reference_grid, method = resampling)
  }
}
names(aligned) <- input_names

# ---- 全部两两组合的全局指标（与窗口大小无关，只计算一次） --------------
pairwise_metrics <- list()
first_pair_key <- NULL
for (left_index in seq_len(length(aligned) - 1L)) {
  for (right_index in (left_index + 1L):length(aligned)) {
    left <- aligned[[left_index]]
    right <- aligned[[right_index]]
    valid_mask <- ifel(is.finite(left) & is.finite(right), 1, NA)
    left_valid <- mask(left, valid_mask)
    right_valid <- mask(right, valid_mask)
    left_values <- values(left_valid, mat = FALSE)
    right_values <- values(right_valid, mat = FALSE)
    ok <- is.finite(left_values) & is.finite(right_values)
    if (!any(ok)) next
    left_values <- left_values[ok]
    right_values <- right_values[ok]
    difference_values <- left_values - right_values
    pair_key <- paste(input_names[left_index], input_names[right_index], sep = "__vs__")
    pair_metrics <- list(
      left = input_names[left_index],
      right = input_names[right_index],
      me = json_number(safe_mean(difference_values)),
      mae = json_number(safe_mean(abs(difference_values))),
      mre = json_number(safe_mre(left_values, right_values)),
      rmse = json_number(safe_rmse(difference_values)),
      correlation = json_number(if (length(left_values) >= 2) cor(left_values, right_values) else NA_real_),
      valid_cells = length(left_values)
    )
    pairwise_metrics[[pair_key]] <- pair_metrics
    if (is.null(first_pair_key)) first_pair_key <- pair_key
  }
}
if (!length(pairwise_metrics)) write_error("栅格之间没有重叠的有效像元")
first_pair_metrics <- pairwise_metrics[[first_pair_key]]
first_pair <- strsplit(first_pair_key, "__vs__", fixed = TRUE)[[1]]
first_left <- aligned[[match(first_pair[[1]], input_names)]]
first_right <- aligned[[match(first_pair[[2]], input_names)]]
names(first_left) <- "left"
names(first_right) <- "right"
first_valid_mask <- ifel(is.finite(first_left) & is.finite(first_right), 1, NA)
first_left_valid <- mask(first_left, first_valid_mask)
first_right_valid <- mask(first_right, first_valid_mask)

# ---- 按窗口大小序列计算局部指标曲线与预览栅格 --------------------------
curve <- list()
local_mae_list <- list()
previews <- list()

for (ws in window_sizes) {
  window <- matrix(1, nrow = ws, ncol = ws)
  absolute_difference <- abs(first_left_valid - first_right_valid)
  relative_difference <- ifel(abs(first_left_valid) > zero_epsilon,
                              absolute_difference / abs(first_left_valid), NA)
  local_mae <- focal(absolute_difference, w = window, fun = safe_mean, na.rm = FALSE, fill = NA)
  local_rmse <- focal(absolute_difference^2, w = window, fun = safe_rms_from_squared, na.rm = FALSE, fill = NA)
  local_n <- focal(first_valid_mask, w = window, fun = sum, na.rm = TRUE, fill = NA)
  local_x <- focal(first_right_valid, w = window, fun = sum, na.rm = TRUE, fill = NA)
  local_y <- focal(first_left_valid, w = window, fun = sum, na.rm = TRUE, fill = NA)
  local_x2 <- focal(first_right_valid^2, w = window, fun = sum, na.rm = TRUE, fill = NA)
  local_y2 <- focal(first_left_valid^2, w = window, fun = sum, na.rm = TRUE, fill = NA)
  local_xy <- focal(first_left_valid * first_right_valid, w = window, fun = sum, na.rm = TRUE, fill = NA)
  local_x_var <- local_x2 - local_x^2 / local_n
  local_y_var <- local_y2 - local_y^2 / local_n
  local_cov <- local_xy - local_x * local_y / local_n
  local_correlation <- ifel(local_n >= 3 & local_x_var > zero_epsilon & local_y_var > zero_epsilon,
                            local_cov / sqrt(local_x_var * local_y_var), NA)
  local_coefficient <- ifel(local_n >= 2 & local_x2 > zero_epsilon, local_xy / local_x2, NA)
  local_residual_ss <- local_y2 - 2 * local_coefficient * local_xy +
    local_coefficient^2 * local_x2
  local_r2 <- ifel(local_n >= 2 & local_y2 > zero_epsilon,
                   1 - local_residual_ss / local_y2, NA)
  local_correlation <- ifel(local_correlation < -1, -1,
                            ifel(local_correlation > 1, 1, local_correlation))
  local_r2 <- ifel(local_r2 < 0, 0, ifel(local_r2 > 1, 1, local_r2))

  # 预览栅格（地图显示用）：降采样到有限边长，压缩写盘
  agg_fact <- max(1L, ceiling(max(dim(local_mae)[1:2]) / preview_max_dim))
  preview_grid <- terra::aggregate(local_mae, fact = agg_fact, fun = "mean", na.rm = TRUE)
  preview_path <- file.path(preview_dir, sprintf("preview_ws%03d_local_mae.tif", ws))
  writeRaster(preview_grid, preview_path, overwrite = TRUE,
              filetype = "GTiff", gdal = c("COMPRESS=LZW"))
  previews[[length(previews) + 1L]] <- preview_path

  # 图例分级用数值网格：更小的降采样，随 JSON 返回
  legend_fact <- max(1L, ceiling(max(dim(local_mae)[1:2]) / legend_max_dim))
  legend_grid <- if (legend_fact == agg_fact) preview_grid else
    terra::aggregate(local_mae, fact = legend_fact, fun = "mean", na.rm = TRUE)
  local_mae_list[[length(local_mae_list) + 1L]] <- values(legend_grid, mat = FALSE)

  curve[[length(curve) + 1L]] <- list(
    bandwidth = as.integer(ws),
    me = json_number(first_pair_metrics$me),
    mae = json_number(first_pair_metrics$mae),
    mre = json_number(first_pair_metrics$mre),
    rmse = json_number(first_pair_metrics$rmse),
    correlation = json_number(first_pair_metrics$correlation),
    local_mae_median = json_number(safe_median(values(local_mae, mat = FALSE))),
    local_rmse_median = json_number(safe_median(values(local_rmse, mat = FALSE))),
    local_r2_median = json_number(safe_median(values(local_r2, mat = FALSE))),
    local_corr_median = json_number(safe_median(values(local_correlation, mat = FALSE))),
    coefficient_median = json_number(safe_median(values(local_coefficient, mat = FALSE)))
  )

  rm(local_mae, local_rmse, local_n, local_x, local_y, local_x2, local_y2, local_xy,
     local_x_var, local_y_var, local_cov, local_correlation, local_coefficient,
     local_residual_ss, local_r2, preview_grid, legend_grid, absolute_difference,
     relative_difference)
}

result <- list(
  status  = "success",
  engine  = "R / terra · 带宽探索",
  message = sprintf("窗口带宽探索完成：%s 个栅格，%s 个窗口大小（%s ~ %s）。",
                    length(raster_paths), length(window_sizes),
                    min(window_sizes), max(window_sizes)),
  curve = curve,
  bandwidths = as.list(window_sizes),
  local_mae = local_mae_list,
  previews = as.list(previews),
  pairwise_metrics = pairwise_metrics,
  config = config
)

jsonlite::write_json(result, output_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
