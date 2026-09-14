args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2) stop("需要 config.json 和 output.json")
config_path <- args[[1]]
output_path <- args[[2]]

# TODO: replace this file with the real R implementation.
# Recommended packages: jsonlite, sf, terra, GWmodel.
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  stop("请先安装 R 包 jsonlite")
}

config <- jsonlite::fromJSON(config_path)
bandwidth <- as.numeric(config$bandwidth)
local_values <- round(pmax(0.45, pmin(0.95, 0.56 + ((0:17 * 13) %% 37) / 100 + bandwidth / 10)), 3)
result <- list(
  status = "success",
  engine = "R 占位算法",
  metrics = list(
    mae = "8.42",
    rmse = "13.67",
    correlation = "0.82",
    local_r2 = sprintf("%.2f", mean(local_values)),
    difference_area = "18.6%",
    duration = "00:03"
  ),
  message = "R 算法适配器已执行。请将本脚本替换为真实预处理或 GWR 实现。",
  local_values = local_values,
  config = config
)
jsonlite::write_json(result, output_path, auto_unbox = TRUE, pretty = TRUE)
