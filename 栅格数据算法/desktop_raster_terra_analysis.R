args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2) {
  stop("Usage: Rscript desktop_raster_terra_analysis.R config.json output.json")
}
if (!requireNamespace("jsonlite", quietly = TRUE)) stop("请先安装 R 包 jsonlite")
`%||%` <- function(a, b) if (is.null(a) || length(a) == 0L) b else a
config <- jsonlite::fromJSON(args[[1]])
result_path <- args[[2]]
reference_file <- config$reference_path
comparison_file <- config$comparison_path
output_dir <- config$output_dir
window_size <- as.integer(config$window_size %||% 5L)
scatter_max_points <- as.integer(config$scatter_max_points %||% 50000L)
zero_epsilon <- as.numeric(config$zero_epsilon %||% 1e-12)
write_local_rasters <- isTRUE(config$write_local_rasters %||% TRUE)
write_scatter_plot <- isTRUE(config$write_scatter_plot %||% TRUE)
resampling <- config$resampling %||% "bilinear"
if (!requireNamespace("terra", quietly = TRUE)) stop("请先安装 R 包 terra")
suppressPackageStartupMessages(library(terra))
if (!file.exists(reference_file) || !file.exists(comparison_file)) stop("栅格输入文件不存在")
if (is.na(window_size) || window_size < 3 || window_size %% 2 != 1) stop("window_size 必须是大于等于 3 的奇数")
dir.create(output_dir, showWarnings = FALSE, recursive = TRUE)
dir.create(file.path(output_dir, "temp"), showWarnings = FALSE, recursive = TRUE)
terraOptions(tempdir = file.path(output_dir, "temp"))

safe_mean <- function(x, ...) {
  x <- x[is.finite(x)]
  if (!length(x)) return(NA_real_)
  mean(x)
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
  if (length(value) == 0 || !is.finite(value)) "null" else sprintf("%.12g", value)
}
write_result <- function(x, filename) {
  writeRaster(x, file.path(output_dir, filename), overwrite = TRUE,
              filetype = "GTiff", gdal = c("COMPRESS=LZW"))
}

reference <- rast(reference_file)
comparison <- rast(comparison_file)
if (nlyr(reference) != 1 || nlyr(comparison) != 1) stop("每个栅格必须只包含一个波段")
names(reference) <- "reference"
names(comparison) <- "comparison"
comparison_aligned <- project(comparison, reference, method = resampling)
names(comparison_aligned) <- "comparison"

valid_mask <- ifel(is.finite(reference) & is.finite(comparison_aligned), 1, NA)
reference_valid <- mask(reference, valid_mask)
comparison_valid <- mask(comparison_aligned, valid_mask)
reference_values <- values(reference_valid, mat = FALSE)
comparison_values <- values(comparison_valid, mat = FALSE)
ok <- is.finite(reference_values) & is.finite(comparison_values)
if (!any(ok)) stop("两个栅格没有重叠的有效像元")
reference_values <- reference_values[ok]
comparison_values <- comparison_values[ok]
difference_values <- reference_values - comparison_values

me <- safe_mean(difference_values)
mae <- safe_mean(abs(difference_values))
mre <- safe_mre(reference_values, comparison_values)
rmse <- safe_rmse(difference_values)
correlation <- if (length(reference_values) >= 2) cor(reference_values, comparison_values) else NA_real_

global_metrics <- data.frame(
  metric = c("ME", "MAE", "MRE", "RMSE", "Pearson_r", "valid_cells"),
  value = c(me, mae, mre, rmse, correlation, length(reference_values))
)
write.csv(global_metrics, file.path(output_dir, "global_metrics.csv"),
          row.names = FALSE, fileEncoding = "UTF-8")

if (write_scatter_plot && requireNamespace("ggplot2", quietly = TRUE) && length(reference_values) >= 3) {
  set.seed(20260914)
  draw_index <- seq_along(reference_values)
  if (length(draw_index) > scatter_max_points) draw_index <- sample(draw_index, scatter_max_points)
  draw_data <- data.frame(comparison = comparison_values[draw_index],
                          reference = reference_values[draw_index])
  plot <- ggplot2::ggplot(draw_data, ggplot2::aes(comparison, reference)) +
    ggplot2::geom_point(color = "#2C6E9E", alpha = 0.18, size = 0.7) +
    ggplot2::geom_abline(intercept = 0, slope = 1, linetype = "dashed") +
    ggplot2::labs(title = "Raster pixel-level comparison",
                  subtitle = paste0("valid cells: ", format(length(reference_values), big.mark = ",")),
                  x = "Comparison", y = "Reference") +
    ggplot2::theme_classic()
  ggplot2::ggsave(file.path(output_dir, "raster_scatter.png"), plot, width = 7.2, height = 6.4, dpi = 180)
}

window <- matrix(1, nrow = window_size, ncol = window_size)
difference <- reference_valid - comparison_valid
absolute_difference <- abs(difference)
relative_difference <- ifel(abs(reference_valid) > zero_epsilon,
                            absolute_difference / abs(reference_valid), NA)
local_me <- focal(difference, w = window, fun = safe_mean, na.rm = FALSE, fill = NA)
local_mae <- focal(absolute_difference, w = window, fun = safe_mean, na.rm = FALSE, fill = NA)
local_mre <- focal(relative_difference, w = window, fun = safe_mean, na.rm = FALSE, fill = NA)
local_rmse <- focal(difference^2, w = window, fun = safe_rms_from_squared, na.rm = FALSE, fill = NA)
if (write_local_rasters) {
  write_result(local_me, "local_ME.tif")
  write_result(local_mae, "local_MAE.tif")
  write_result(local_mre, "local_MRE.tif")
  write_result(local_rmse, "local_RMSE.tif")
}

local_n <- focal(valid_mask, w = window, fun = sum, na.rm = TRUE, fill = NA)
local_x <- focal(comparison_valid, w = window, fun = sum, na.rm = TRUE, fill = NA)
local_y <- focal(reference_valid, w = window, fun = sum, na.rm = TRUE, fill = NA)
local_x2 <- focal(comparison_valid^2, w = window, fun = sum, na.rm = TRUE, fill = NA)
local_y2 <- focal(reference_valid^2, w = window, fun = sum, na.rm = TRUE, fill = NA)
local_xy <- focal(reference_valid * comparison_valid, w = window, fun = sum, na.rm = TRUE, fill = NA)
local_x_var <- local_x2 - local_x^2 / local_n
local_y_var <- local_y2 - local_y^2 / local_n
local_cov <- local_xy - local_x * local_y / local_n
local_correlation <- ifel(local_n >= 3 & local_x_var > 1e-12 & local_y_var > 1e-12,
                           local_cov / sqrt(local_x_var * local_y_var), NA)
local_coefficient <- ifel(local_n >= 2 & local_x2 > 1e-12, local_xy / local_x2, NA)
local_residual_ss <- local_y2 - 2 * local_coefficient * local_xy +
  local_coefficient^2 * local_x2
local_r2 <- ifel(local_n >= 2 & local_y2 > 1e-12,
                 1 - local_residual_ss / local_y2, NA)
local_correlation <- ifel(local_correlation < -1, -1,
                          ifel(local_correlation > 1, 1, local_correlation))
local_r2 <- ifel(local_r2 < 0, 0, ifel(local_r2 > 1, 1, local_r2))
if (write_local_rasters) {
  write_result(local_correlation, "local_correlation.tif")
  write_result(local_coefficient, "local_coefficient_no_intercept.tif")
  write_result(local_r2, "local_R2_no_intercept.tif")
  write_result(reference_valid, "reference_aligned.tif")
  write_result(comparison_valid, "comparison_aligned.tif")
}
local_preview <- values(local_mae, mat = FALSE)
local_preview <- local_preview[is.finite(local_preview)]
local_preview <- head(local_preview, 1000)

artifact_names <- character()
if (write_local_rasters) {
  artifact_names <- c(
    "local_ME.tif", "local_MAE.tif", "local_MRE.tif", "local_RMSE.tif",
    "local_correlation.tif", "local_coefficient_no_intercept.tif",
    "local_R2_no_intercept.tif", "reference_aligned.tif", "comparison_aligned.tif"
  )
}
if (write_scatter_plot && file.exists(file.path(output_dir, "raster_scatter.png"))) {
  artifact_names <- c(artifact_names, "raster_scatter.png")
}
artifacts <- as.list(file.path(output_dir, artifact_names))
names(artifacts) <- tools::file_path_sans_ext(artifact_names)
result <- list(
  status = "success",
  engine = "R / terra",
  message = "栅格异源同质分析完成",
  metrics = list(
    me = me, mae = mae, mre = mre, rmse = rmse,
    correlation = correlation, valid_cells = length(reference_values)
  ),
  output_dir = output_dir,
  artifacts = artifacts,
  local_values = local_preview
)
jsonlite::write_json(result, result_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
jsonlite::write_json(result, file.path(output_dir, "result.json"), auto_unbox = TRUE, pretty = TRUE, na = "null")
