# ============================================================================
#  R 依赖清单
# ----------------------------------------------------------------------------
#  一键安装全部 R 包（在 desktop_client 目录下运行）：
#    Rscript requirements.R
#  或指定 Rscript 完整路径：
#    & "C:\Program Files\R\R-4.5.3\bin\x64\Rscript.exe" requirements.R
#  只安装缺失的包，已安装的会跳过。
# ============================================================================

pkgs <- c(
  "jsonlite",   # 算法适配器 JSON 读写（必需）
  "sf",         # 属性数据 GWR（必需）
  "GWmodel",    # 属性数据 GWR（必需）
  "sp",         # 属性数据 GWR（必需）
  "terra",      # 栅格分析（必需）
  "ggplot2"     # 输出散点图（可选，不装不影响核心统计）
)

repos <- "https://cloud.r-project.org"
missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) {
  install.packages(missing, repos = repos)
} else {
  cat("所有 R 包均已安装：", paste(pkgs, collapse = ", "), "\n")
}
