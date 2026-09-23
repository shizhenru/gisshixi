args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2) {
  stop("Usage: Rscript desktop_raster_terra_analysis.R config.json output.json")
}
if (!requireNamespace("jsonlite", quietly = TRUE)) stop("请先安装 R 包 jsonlite")
if (!requireNamespace("terra", quietly = TRUE)) stop("请先安装 R 包 terra")

`%||%` <- function(a, b) if (is.null(a) || length(a) == 0L) b else a
config <- jsonlite::fromJSON(args[[1]])
result_path <- args[[2]]
output_dir <- config$output_dir
window_size <- as.integer(config$window_size %||% 5L)
scatter_max_points <- as.integer(config$scatter_max_points %||% 50000L)
zero_epsilon <- as.numeric(config$zero_epsilon %||% 1e-12)
write_local_rasters <- isTRUE(config$write_local_rasters %||% TRUE)
write_scatter_plot <- isTRUE(config$write_scatter_plot %||% TRUE)
python_scatter_plot <- isTRUE(config$python_scatter_plot %||% FALSE)
resampling <- config$resampling %||% "bilinear"

raster_paths <- config$raster_paths %||% character()
if (!length(raster_paths)) {
  raster_paths <- c(config$reference_path %||% "", config$comparison_path %||% "")
}
raster_paths <- as.character(raster_paths[nzchar(raster_paths)])
if (length(raster_paths) < 2) stop("栅格分析至少需要两个栅格数据集")
if (any(!file.exists(raster_paths))) stop("栅格输入文件不存在")
if (is.na(window_size) || window_size < 3 || window_size %% 2 != 1) {
  stop("window_size 必须是大于等于 3 的奇数")
}

dir.create(output_dir, showWarnings = FALSE, recursive = TRUE)
dir.create(file.path(output_dir, "temp"), showWarnings = FALSE, recursive = TRUE)
suppressPackageStartupMessages(library(terra))
terraOptions(tempdir = file.path(output_dir, "temp"))

safe_mean <- function(x, ...) {
  x <- x[is.finite(x)]
  if (!length(x)) {
    return(NA_real_)
  }
  mean(x)
}
safe_median <- function(x, ...) {
  x <- x[is.finite(x)]
  if (!length(x)) {
    return(NA_real_)
  }
  median(x)
}
safe_statistics <- function(x) {
  x <- x[is.finite(x)]
  if (!length(x)) {
    return(list(
      count = 0L, min = NA_real_, q1 = NA_real_, median = NA_real_,
      q3 = NA_real_, max = NA_real_, mean = NA_real_, sd = NA_real_
    ))
  }
  quartiles <- quantile(x, probs = c(0.25, 0.5, 0.75), na.rm = TRUE, names = FALSE)
  list(
    count = length(x),
    min = min(x),
    q1 = quartiles[[1]],
    median = quartiles[[2]],
    q3 = quartiles[[3]],
    max = max(x),
    mean = mean(x),
    sd = if (length(x) >= 2) sd(x) else NA_real_
  )
}
safe_rmse <- function(x, ...) {
  x <- x[is.finite(x)]
  if (!length(x)) {
    return(NA_real_)
  }
  sqrt(mean(x^2))
}
safe_rms_from_squared <- function(x, ...) {
  x <- x[is.finite(x)]
  if (!length(x)) {
    return(NA_real_)
  }
  sqrt(mean(x))
}
safe_mre <- function(reference, comparison) {
  ok <- is.finite(reference) & is.finite(comparison) & abs(reference) > zero_epsilon
  if (!any(ok)) {
    return(NA_real_)
  }
  mean(abs((reference[ok] - comparison[ok]) / reference[ok]))
}
json_number <- function(value) {
  if (length(value) == 0 || !is.finite(value)) NA_real_ else value
}
write_result <- function(x, filename) {
  writeRaster(x, file.path(output_dir, filename),
    overwrite = TRUE,
    filetype = "GTiff", gdal = c("COMPRESS=LZW")
  )
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
display_names <- input_names
input_names <- make.unique(vapply(input_names, safe_name, character(1)))

rasters <- lapply(raster_paths, terra::rast)
if (any(vapply(rasters, terra::nlyr, numeric(1)) != 1)) {
  stop("每个栅格必须只包含一个波段")
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

window <- matrix(1, nrow = window_size, ncol = window_size)
artifact_names <- character()
pairwise_metrics <- list()
local_statistics <- list()
first_pair_metrics <- NULL
first_local_preview <- numeric()

for (left_index in seq_len(length(aligned) - 1L)) {
  for (right_index in (left_index + 1L):length(aligned)) {
    left <- aligned[[left_index]]
    right <- aligned[[right_index]]
    names(left) <- "left"
    names(right) <- "right"
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
    correlation <- if (length(left_values) >= 2) cor(left_values, right_values) else NA_real_
    pair_key <- paste(input_names[left_index], input_names[right_index], sep = "__vs__")
    pair_metrics <- list(
      left = input_names[left_index],
      right = input_names[right_index],
      me = json_number(safe_mean(difference_values)),
      mae = json_number(safe_mean(abs(difference_values))),
      mre = json_number(safe_mre(left_values, right_values)),
      rmse = json_number(safe_rmse(difference_values)),
      correlation = json_number(correlation),
      valid_cells = length(left_values)
    )
    pairwise_metrics[[pair_key]] <- pair_metrics
    if (is.null(first_pair_metrics)) first_pair_metrics <- pair_metrics

    if (write_local_rasters) {
      prefix <- paste0(safe_name(input_names[left_index]), "__vs__", safe_name(input_names[right_index]))
      difference <- left_valid - right_valid
      absolute_difference <- abs(difference)
      relative_difference <- ifel(
        abs(left_valid) > zero_epsilon,
        absolute_difference / abs(left_valid), NA
      )
      local_me <- focal(difference, w = window, fun = safe_mean, na.rm = FALSE, fill = NA)
      local_mae <- focal(absolute_difference, w = window, fun = safe_mean, na.rm = FALSE, fill = NA)
      local_mre <- focal(relative_difference, w = window, fun = safe_mean, na.rm = FALSE, fill = NA)
      local_rmse <- focal(difference^2, w = window, fun = safe_rms_from_squared, na.rm = FALSE, fill = NA)
      local_n <- focal(valid_mask, w = window, fun = sum, na.rm = TRUE, fill = NA)
      local_x <- focal(right_valid, w = window, fun = sum, na.rm = TRUE, fill = NA)
      local_y <- focal(left_valid, w = window, fun = sum, na.rm = TRUE, fill = NA)
      local_x2 <- focal(right_valid^2, w = window, fun = sum, na.rm = TRUE, fill = NA)
      local_y2 <- focal(left_valid^2, w = window, fun = sum, na.rm = TRUE, fill = NA)
      local_xy <- focal(left_valid * right_valid, w = window, fun = sum, na.rm = TRUE, fill = NA)
      local_x_var <- local_x2 - local_x^2 / local_n
      local_y_var <- local_y2 - local_y^2 / local_n
      local_cov <- local_xy - local_x * local_y / local_n
      local_correlation <- ifel(
        local_n >= 3 & local_x_var > zero_epsilon & local_y_var > zero_epsilon,
        local_cov / sqrt(local_x_var * local_y_var), NA
      )
      local_coefficient <- ifel(local_n >= 2 & local_x2 > zero_epsilon, local_xy / local_x2, NA)
      local_residual_ss <- local_y2 - 2 * local_coefficient * local_xy +
        local_coefficient^2 * local_x2
      local_r2 <- ifel(
        local_n >= 2 & local_y2 > zero_epsilon,
        1 - local_residual_ss / local_y2, NA
      )
      local_correlation <- ifel(
        local_correlation < -1, -1,
        ifel(local_correlation > 1, 1, local_correlation)
      )
      local_r2 <- ifel(local_r2 < 0, 0, ifel(local_r2 > 1, 1, local_r2))
      outputs <- list(
        local_ME = local_me, local_MAE = local_mae, local_MRE = local_mre,
        local_RMSE = local_rmse, local_correlation = local_correlation,
        local_coefficient_no_intercept = local_coefficient,
        local_R2_no_intercept = local_r2,
        left_aligned = left_valid, right_aligned = right_valid
      )
      local_statistics[[pair_key]] <- list(
        local_r2 = safe_statistics(values(local_r2, mat = FALSE)),
        coefficient = safe_statistics(values(local_coefficient, mat = FALSE)),
        local_corr = safe_statistics(values(local_correlation, mat = FALSE)),
        lme = safe_statistics(values(local_me, mat = FALSE)),
        lmae = safe_statistics(values(local_mae, mat = FALSE)),
        lmre = safe_statistics(values(local_mre, mat = FALSE)),
        lrmse = safe_statistics(values(local_rmse, mat = FALSE))
      )
      for (output_name in names(outputs)) {
        filename <- paste0(prefix, "__", output_name, ".tif")
        write_result(outputs[[output_name]], filename)
        artifact_names <- c(artifact_names, filename)
      }
      if (!length(first_local_preview)) {
        first_local_preview <- values(local_mae, mat = FALSE)
        first_local_preview <- head(first_local_preview[is.finite(first_local_preview)], 1000)
        first_pair_metrics$local_r2_median <- local_statistics[[pair_key]]$local_r2$median
        first_pair_metrics$coefficient_median <- local_statistics[[pair_key]]$coefficient$median
        first_pair_metrics$local_corr_median <- local_statistics[[pair_key]]$local_corr$median
        first_pair_metrics$lme_median <- local_statistics[[pair_key]]$lme$median
        first_pair_metrics$lmae_median <- local_statistics[[pair_key]]$lmae$median
        first_pair_metrics$lmre_median <- local_statistics[[pair_key]]$lmre$median
        first_pair_metrics$lrmse_median <- local_statistics[[pair_key]]$lrmse$median
      }
    }
  }
}
if (!length(pairwise_metrics)) stop("栅格之间没有重叠的有效像元")

if (write_scatter_plot) {
  matrix_values <- lapply(aligned, function(raster) values(raster, mat = FALSE))
  scatter_data <- as.data.frame(matrix_values, check.names = FALSE)
  names(scatter_data) <- input_names
  scatter_data <- scatter_data[complete.cases(scatter_data), , drop = FALSE]
  if (nrow(scatter_data) >= 3) {
    set.seed(20260917)
    draw_data <- scatter_data
    if (nrow(draw_data) > scatter_max_points) {
      draw_data <- draw_data[sample.int(nrow(draw_data), scatter_max_points), , drop = FALSE]
    }
    write.csv(draw_data, file.path(output_dir, "raster_scatter_data.csv"), row.names = FALSE)
    if (!python_scatter_plot) {
      panel_scatter <- function(x, y, ...) {
        points(x, y, pch = 16, col = grDevices::adjustcolor("#2C6E9E", alpha.f = 0.18), cex = 0.45)
        finite <- is.finite(x) & is.finite(y)
        if (!any(finite)) {
          return()
        }
        abline(a = 0, b = 1, col = "#777777", lty = 2, lwd = 1)
        if (sum(finite) >= 2 && sum(x[finite]^2) > 0) {
          fit <- lm(y[finite] ~ x[finite] - 1)
          abline(fit, col = "#C43D3D", lwd = 1.2)
        }
      }
      panel_hist <- function(x, ...) {
        x <- x[is.finite(x)]
        if (!length(x)) {
          return()
        }
        histogram <- hist(x, plot = FALSE, breaks = 20)
        rect(histogram$breaks[-length(histogram$breaks)], 0,
          histogram$breaks[-1], histogram$counts,
          col = "#B9D8D1", border = "white"
        )
      }
      matrix_png <- file.path(output_dir, "raster_scatter_matrix.png")
      grDevices::png(matrix_png,
        width = max(1200, 420 * length(input_names)),
        height = max(1200, 420 * length(input_names)), res = 150
      )
      pairs(draw_data,
        lower.panel = panel_scatter, upper.panel = panel_scatter,
        diag.panel = panel_hist, labels = input_names,
        main = "Raster pixel scatterplot matrix"
      )
      grDevices::dev.off()
      matrix_pdf <- file.path(output_dir, "raster_scatter_matrix.pdf")
      grDevices::pdf(matrix_pdf,
        width = max(7, 2.8 * length(input_names)),
        height = max(7, 2.8 * length(input_names))
      )
      pairs(draw_data,
        lower.panel = panel_scatter, upper.panel = panel_scatter,
        diag.panel = panel_hist, labels = input_names,
        main = "Raster pixel scatterplot matrix"
      )
      grDevices::dev.off()
      artifact_names <- c(artifact_names, "raster_scatter_matrix.png", "raster_scatter_matrix.pdf")
    }
  }
}

artifacts <- as.list(file.path(output_dir, artifact_names))
names(artifacts) <- tools::file_path_sans_ext(artifact_names)
result <- list(
  status = "success",
  engine = "R / terra",
  message = paste0(
    "栅格多数据集分析完成：", length(raster_paths), " 个栅格，",
    length(pairwise_metrics), " 组两两比较"
  ),
  raster_names = input_names,
  raster_display_names = display_names,
  pairwise_metrics = pairwise_metrics,
  local_statistics = local_statistics,
  metrics = first_pair_metrics,
  output_dir = output_dir,
  artifacts = artifacts,
  local_values = first_local_preview
)
jsonlite::write_json(result, result_path, auto_unbox = TRUE, pretty = TRUE, na = "null")
jsonlite::write_json(result, file.path(output_dir, "result.json"), auto_unbox = TRUE, pretty = TRUE, na = "null")
