# Raster-based validation for two heterogeneous-but-homogeneous night-light datasets.
# The workflow keeps the original ME, MAE, MRE and RMSE indicators and
# approximates geographically weighted analysis with moving-window local statistics.

suppressPackageStartupMessages({
  library(terra)
})

# ----------------------------- User settings -----------------------------
# Replace these paths with the names of your two input GeoTIFF files.
reference_file <- "../\u6B66\u6C49\u591C\u5149\u9065\u611F/wh_cnviirs.tif"
comparison_file <- "../\u6B66\u6C49\u591C\u5149\u9065\u611F/wh_nasa.tif"
comparison_file2 <- "../\u6B66\u6C49\u591C\u5149\u9065\u611F/wh_eog-vnl.tif"
# Use an ASCII-only output path because R 4.6.1 on Windows can fail to
# translate temporary/output paths containing Chinese characters.
output_dir <- "C:/Users/PC/.codex/visualizations/2026/09/11/01a08f46-0bd4-7a22-85cd-1960dc2716b6/terra_results"

# Moving-window size. Use an odd number such as 3, 5 or 7.
window_size <- 5

# Maximum number of points drawn in the scatter plot. All valid pixels are
# still used to calculate the statistics and regression coefficients.
scatter_max_points <- 50000
scatter_seed <- 20260911

# Continuous night-light data should normally use bilinear resampling.
resample_method <- "bilinear"

# Relative error is undefined where the denominator is zero.
zero_epsilon <- 1e-12

# ----------------------------- Helper functions ----------------------------
check_input_file <- function(path) {
  if (!file.exists(path)) {
    stop("Input file does not exist: ", path)
  }
}

check_window_size <- function(size) {
  if (length(size) != 1L || !is.numeric(size) ||
      size < 3 || size %% 2 != 1) {
    stop("window_size must be an odd number greater than or equal to 3.")
  }
}

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

safe_mre <- function(reference, comparison, epsilon = 1e-12) {
  ok <- is.finite(reference) & is.finite(comparison) &
    abs(reference) > epsilon
  if (!any(ok)) return(NA_real_)
  mean(abs((reference[ok] - comparison[ok]) / reference[ok]))
}

write_result <- function(raster, filename) {
  writeRaster(
    raster,
    file.path(output_dir, filename),
    overwrite = TRUE,
    filetype = "GTiff",
    gdal = c("COMPRESS=LZW")
  )
}

# ----------------------------- Input and alignment -------------------------
check_input_file(reference_file)
check_input_file(comparison_file)
check_window_size(window_size)
dir.create(output_dir, showWarnings = FALSE, recursive = TRUE)
terra_temp_dir <- file.path(output_dir, "temp")
dir.create(terra_temp_dir, showWarnings = FALSE, recursive = TRUE)
terraOptions(tempdir = terra_temp_dir)

reference <- rast(reference_file)
comparison <- rast(comparison_file)

if (nlyr(reference) != 1 || nlyr(comparison) != 1) {
  stop("Each input GeoTIFF must contain exactly one layer.")
}

names(reference) <- "reference"
names(comparison) <- "comparison"

# Align comparison to the reference grid. This handles different CRS,
# resolution, extent and origin while preserving the reference grid.
comparison_aligned <- project(
  comparison,
  reference,
  method = resample_method
)
names(comparison_aligned) <- "comparison"

# Keep only locations where both datasets contain valid values.
valid_mask <- ifel(
  is.finite(reference) & is.finite(comparison_aligned),
  1,
  NA
)
reference_valid <- mask(reference, valid_mask)
comparison_valid <- mask(comparison_aligned, valid_mask)

pair <- c(reference_valid, comparison_valid)
names(pair) <- c("reference", "comparison")

# Extract valid paired values once for the global statistics and validation.
reference_values <- values(reference_valid, mat = FALSE)
comparison_values <- values(comparison_valid, mat = FALSE)

if (!any(is.finite(reference_values) & is.finite(comparison_values))) {
  stop("The two rasters have no overlapping valid cells.")
}

# ----------------------------- Global indicators ---------------------------
difference_values <- reference_values - comparison_values
absolute_difference_values <- abs(difference_values)

global_metrics <- data.frame(
  metric = c("ME", "MAE", "MRE", "RMSE"),
  value = c(
    safe_mean(difference_values),
    safe_mean(absolute_difference_values),
    safe_mre(reference_values, comparison_values, zero_epsilon),
    safe_rmse(difference_values)
  )
)

write.csv(
  global_metrics,
  file.path(output_dir, "global_metrics.csv"),
  row.names = FALSE,
  fileEncoding = "UTF-8"
)

# ----------------------------- Scatter plot -------------------------------
# A publication-style scatter plot showing the pixel-level relationship
# between the two aligned datasets.
if (!requireNamespace("ggplot2", quietly = TRUE)) {
  stop(
    "The scatter plot requires ggplot2. Install it with: ",
    "install.packages('ggplot2')"
  )
}

scatter_data <- data.frame(
  comparison = comparison_values,
  reference = reference_values
)
scatter_data <- scatter_data[
  is.finite(scatter_data$comparison) &
    is.finite(scatter_data$reference),
  ,
  drop = FALSE
]

if (nrow(scatter_data) < 3) {
  stop("At least three valid paired pixels are required for the scatter plot.")
}

set.seed(scatter_seed)
draw_data <- scatter_data
if (nrow(draw_data) > scatter_max_points) {
  draw_data <- draw_data[
    sample.int(nrow(draw_data), scatter_max_points),
    ,
    drop = FALSE
  ]
}

scatter_fit <- lm(reference ~ comparison - 1, data = scatter_data)
scatter_r <- cor(
  scatter_data$comparison,
  scatter_data$reference,
  use = "complete.obs"
)
scatter_r2 <- summary(scatter_fit)$r.squared
scatter_slope <- unname(coef(scatter_fit)[["comparison"]])

axis_max <- max(
  scatter_data$comparison,
  scatter_data$reference,
  na.rm = TRUE
)
axis_min <- min(
  scatter_data$comparison,
  scatter_data$reference,
  na.rm = TRUE
)
axis_limits <- c(axis_min, axis_max)

annotation_text <- paste0(
  "n = ", format(nrow(scatter_data), big.mark = ","), "\n",
  "Pearson r = ", sprintf("%.3f", scatter_r), "\n",
  "R^2 (no intercept) = ", sprintf("%.3f", scatter_r2), "\n",
  "slope = ", sprintf("%.3f", scatter_slope)
)

scatter_plot <- ggplot2::ggplot(
  draw_data,
  ggplot2::aes(x = comparison, y = reference)
) +
  ggplot2::geom_point(
    color = "#2C6E9E",
    alpha = 0.18,
    size = 0.7,
    stroke = 0
  ) +
  ggplot2::geom_abline(
    intercept = 0,
    slope = 1,
    color = "#4D4D4D",
    linewidth = 0.8,
    linetype = "dashed"
  ) +
  ggplot2::geom_smooth(
    method = "lm",
    formula = y ~ x - 1,
    se = FALSE,
    color = "#C43D3D",
    linewidth = 1.0
  ) +
  ggplot2::annotate(
    "text",
    x = axis_min + 0.04 * diff(axis_limits),
    y = axis_max - 0.05 * diff(axis_limits),
    label = annotation_text,
    hjust = 0,
    vjust = 1,
    size = 4.0,
    color = "#222222"
  ) +
  ggplot2::coord_equal(
    xlim = axis_limits,
    ylim = axis_limits,
    expand = FALSE
  ) +
  ggplot2::labs(
    x = "NASA night-light value",
    y = "CNVIIRS night-light value",
    title = "Pixel-level comparison of night-light datasets",
    subtitle = "Dashed line: 1:1 agreement; red line: no-intercept fit"
  ) +
  ggplot2::theme_classic(base_size = 12) +
  ggplot2::theme(
    plot.title = ggplot2::element_text(
      face = "bold",
      size = 14,
      color = "#1A1A1A"
    ),
    plot.subtitle = ggplot2::element_text(
      size = 10.5,
      color = "#4D4D4D"
    ),
    axis.title = ggplot2::element_text(
      face = "bold",
      color = "#1A1A1A"
    ),
    axis.text = ggplot2::element_text(color = "#333333"),
    axis.line = ggplot2::element_line(
      color = "#222222",
      linewidth = 0.5
    ),
    panel.grid = ggplot2::element_blank(),
    plot.margin = ggplot2::margin(10, 14, 10, 10)
  )

ggplot2::ggsave(
  file.path(output_dir, "nightlight_scatter.png"),
  scatter_plot,
  width = 7.2,
  height = 6.4,
  units = "in",
  dpi = 300,
  bg = "white"
)
ggplot2::ggsave(
  file.path(output_dir, "nightlight_scatter.pdf"),
  scatter_plot,
  width = 7.2,
  height = 6.4,
  units = "in",
  device = grDevices::cairo_pdf,
  bg = "white"
)

# ----------------------------- Local indicators ----------------------------
# These moving-window statistics are the raster equivalent of local
# geographically weighted validation. The window is centered on each cell.
window <- matrix(1, nrow = window_size, ncol = window_size)

difference <- reference_valid - comparison_valid
absolute_difference <- abs(difference)
relative_difference <- ifel(
  abs(reference_valid) > zero_epsilon,
  absolute_difference / abs(reference_valid),
  NA
)
squared_difference <- difference^2

local_me <- focal(difference, w = window, fun = safe_mean,
                  na.rm = FALSE, fill = NA)
local_mae <- focal(absolute_difference, w = window, fun = safe_mean,
                   na.rm = FALSE, fill = NA)
local_mre <- focal(relative_difference, w = window, fun = safe_mean,
                   na.rm = FALSE, fill = NA)
local_rmse <- focal(squared_difference, w = window, fun = safe_rmse,
                    na.rm = FALSE, fill = NA)

write_result(local_me, "local_ME.tif")
write_result(local_mae, "local_MAE.tif")
write_result(local_mre, "local_MRE.tif")
write_result(local_rmse, "local_RMSE.tif")

# Local relationship statistics corresponding to the original GWR outputs.
# The sums are calculated separately because terra applies focal statistics
# layer by layer for a multi-layer SpatRaster.
local_n <- focal(valid_mask, w = window, fun = sum, na.rm = TRUE, fill = NA)
local_x <- focal(comparison_valid, w = window, fun = sum, na.rm = TRUE, fill = NA)
local_y <- focal(reference_valid, w = window, fun = sum, na.rm = TRUE, fill = NA)
local_x2 <- focal(comparison_valid^2, w = window, fun = sum,
                  na.rm = TRUE, fill = NA)
local_y2 <- focal(reference_valid^2, w = window, fun = sum,
                  na.rm = TRUE, fill = NA)
local_xy <- focal(reference_valid * comparison_valid, w = window, fun = sum,
                  na.rm = TRUE, fill = NA)

local_x_mean <- local_x / local_n
local_y_mean <- local_y / local_n
local_x_var <- local_x2 - local_x^2 / local_n
local_y_var <- local_y2 - local_y^2 / local_n
local_cov <- local_xy - local_x * local_y / local_n

local_correlation <- ifel(
  local_n >= 3 & local_x_var > zero_epsilon & local_y_var > zero_epsilon,
  local_cov / sqrt(local_x_var * local_y_var),
  NA
)
local_correlation <- ifel(local_correlation < -1, -1, local_correlation)
local_correlation <- ifel(local_correlation > 1, 1, local_correlation)

# No-intercept local coefficient, matching reference ~ comparison - 1.
local_coefficient <- ifel(
  local_n >= 2 & local_x2 > zero_epsilon,
  local_xy / local_x2,
  NA
)

# No-intercept local R2, matching the original regression form.
local_residual_ss <- local_y2 - 2 * local_coefficient * local_xy +
  local_coefficient^2 * local_x2
local_r2 <- ifel(
  local_n >= 2 & local_y2 > zero_epsilon,
  1 - local_residual_ss / local_y2,
  NA
)
local_r2 <- ifel(local_r2 < 0, 0, local_r2)
local_r2 <- ifel(local_r2 > 1, 1, local_r2)

write_result(local_correlation, "local_correlation.tif")
write_result(local_coefficient, "local_coefficient_no_intercept.tif")
write_result(local_r2, "local_R2_no_intercept.tif")

# Save the aligned rasters for reproducibility and later mapping.
write_result(reference_valid, "reference_aligned.tif")
write_result(comparison_valid, "comparison_aligned.tif")

cat("Raster validation completed.\n")
cat("Global metrics:\n")
print(global_metrics)
cat("Output directory:", normalizePath(output_dir, mustWork = FALSE), "\n")
