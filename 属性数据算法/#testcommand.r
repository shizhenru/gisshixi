# ============================================================================
#  多源人口数据 · 地理加权回归(GWR)两两比较分析
# ============================================================================
#  用途 : 输入任意 X / Y 两个字段, 自动完成:
#         (1) 全局统计量  ME / MAE / MRE / RMSE / 相关系数
#         (2) 局部统计量  局部相关系数(gwss)、局部误差 LME/LMAE/LMRE/LRMSE(gwmv)、
#                         局部回归系数与局部 R²(gwr.basic)
#         (3) 输出对应 X/Y 的图表(散点图、误差直方图、局部R²直方图、系数直方图、专题图)
#  约定 : GWR 回归方向为 Y ~ X(用 X 拟合 Y); 误差统一为 Y - X(负=Y低于X, 正=Y高于X)
#  运行 : 工作目录设为项目根目录, 再 Rscript 本文件; 依赖 sf/GWmodel/sp/ggplot2
# ============================================================================

# 定位脚本所在目录, 使 source("gwmv.r") 不依赖"工作目录"
SCRIPT_DIR <- (function() {
  a <- commandArgs(trailingOnly = FALSE)
  f <- sub("^--file=", "", a[grepl("^--file=", a)])
  if (length(f)) return(dirname(normalizePath(f[1])))
  getwd()
})()


# 〇、可调参数区 (PARAMETERS) ===============================================
# 只需要改这里的参数即可重新出结果。

## ---- 数据输入 ----
SHP_PATH <- "data/2024_pop_result.shp"   # 输入 shapefile 路径

## ---- 分析对象: 要分析的 X / Y 字段对 ----
# 每行 c(x = "X字段", y = "Y字段"), 想分析几对就写几行; 不分析写 list()。
# 约定: GWR 用 Y ~ X(横轴 X, 纵轴 Y); 误差 = Y - X。
PAIRS <- list(
  c(x = "worldpop", y = "pop2024"),   # 用 worldpop 拟合 pop2024
  c(x = "ORNL_pop", y = "pop2024"),   # 用 ORNL_pop 拟合 pop2024
  c(x = "ORNL_pop", y = "worldpop")   # 用 ORNL_pop 拟合 worldpop
)

## ---- 空间设置 ----
# 投影到 China Albers 等积圆锥投影(米), 保证 GWR 距离度量正确。
PROJ_CRS <- "+proj=aea +lat_1=25 +lat_2=47 +lat_0=0 +lon_0=105 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"

## ---- GWR 核心设置 ----
KERNEL   <- "bisquare"   # 核函数: bisquare / gaussian / exponential / tricube / boxcar
ADAPTIVE <- TRUE         # TRUE=自适应带宽(近邻个数); FALSE=固定距离带宽(米)
BW_MODE  <- "fixed"      # "fixed"=用下面 BW 的固定值; "auto"=按 AIC 自动求最优
BW       <- 25           # ADAPTIVE=TRUE 时是"最近邻个数"; FALSE 时是"距离(米)"
#   ★ 带宽含义: 每个城市的局部回归只用它最近的 BW 个邻居, 越近权重越大。
#     带宽越大→越平滑(全局); 越小→越局部(分层设色更"碎"), 但太小会过拟合噪声。

## ---- 输出设置 ----
OUT_DIR   <- "results"    # 输出目录(自动创建)
WRITE_SHP <- TRUE         # 是否写出结果 shapefile
WRITE_PNG <- TRUE         # 是否画出图表 PNG
FIG_W <- 8; FIG_H <- 6; FIG_DPI <- 300   # 图尺寸/分辨率

## ---- 图表开关(哪些图要画) ----
PLOT_SCATTER   <- TRUE    # 散点图: X vs Y
PLOT_ERR_HIST  <- TRUE    # 误差直方图: (Y - X) 的分布
PLOT_R2_HIST   <- TRUE    # 局部 R² 直方图
PLOT_COEF_HIST <- TRUE    # GWR 斜率系数直方图
PLOT_MAP       <- TRUE    # 空间专题图: 局部 R² 与 LME


# 一、加载依赖包 =============================================================
suppressPackageStartupMessages({
  library(sf)          # 空间矢量数据读写
  library(GWmodel)     # 地理加权回归
  library(sp)          # GWmodel 底层空间对象
  library(ggplot2)     # 绘图
  library(RColorBrewer)
  library(scales)
})
sf_use_s2(FALSE)
source(file.path(SCRIPT_DIR, "gwmv.r"))   # 局部验证指标函数(与脚本同目录)
dir.create(OUT_DIR, showWarnings = FALSE)


# 二、读取与清洗数据 =========================================================
pop <- st_read(SHP_PATH, quiet = TRUE)
# 重命名(输入文件原始字段顺序固定): name, gb, Province_n, X2024_pop, worldpop, ORNL_pop, geometry
names(pop) <- c("name", "gb", "Province", "pop2024", "worldpop", "ORNL_pop", "geometry")

# 剔除参与分析的字段中存在缺失值的行(台湾/港澳/自然保护区/农场等)
used <- unique(unlist(lapply(PAIRS, function(p) c(p[["x"]], p[["y"]]))))
n0 <- nrow(pop)
pop <- pop[complete.cases(st_drop_geometry(pop)[, used, drop = FALSE]), ]
cat("== 数据清洗 ==\n")
cat("剔除缺失值记录:", n0 - nrow(pop), "条; 有效样本:", nrow(pop), "\n\n")


# 三、投影 ===================================================================
pop <- st_transform(pop, PROJ_CRS)
pop_sp <- as(pop, "Spatial")     # gwss 只接受 Spatial*/data.frame


# 四、辅助函数 ===============================================================
# 全局统计量(约定: 误差 = Y - X)
#  ME   = mean(Y - X)            平均误差(偏置), 负=X 整体大于 Y
#  MAE  = mean(|Y - X|)          平均绝对误差
#  MRE  = mean(|Y - X| / X)      平均相对误差(以 X 为分母)
#  RMSE = sqrt(mean((Y - X)^2))  均方根误差(对大误差更敏感)
#  Corr = cor(Y, X)              皮尔逊相关系数
global_stats <- function(y, x) {
  d <- y - x
  mre <- if (any(x == 0)) mean(abs(d[x != 0]) / x[x != 0]) else mean(abs(d) / x)
  c(ME = mean(d), MAE = mean(abs(d)), MRE = mre,
    RMSE = sqrt(mean(d^2)), Corr = cor(y, x))
}

save_fig <- function(gg, fname) {
  if (!WRITE_PNG) return(invisible(NULL))
  path <- file.path(OUT_DIR, fname)
  if (file.exists(path)) try(unlink(path), silent = TRUE)   # 先删旧图, 避免被查看器占用
  ok <- tryCatch({ ggsave(path, plot = gg, width = FIG_W, height = FIG_H, dpi = FIG_DPI); TRUE },
                 error = function(e) FALSE)
  if (ok) cat("  已出图:", path, "\n")
  else cat("  ! 出图失败(文件可能被占用):", path, "\n")
  invisible(ok)
}

# 散点图: 每个城市一个点, 横轴 X, 纵轴 Y。
#   - 黑色虚线 = 1:1 线(两字段若完全一致, 点落在线上)
#   - 红色线 = 最小二乘回归线(整体趋势)
#   - 左上角标注 R/RMSE/MAE/ME(ME = mean(Y - X))
plot_scatter <- function(d0, xvar, yvar) {
  st <- global_stats(d0[[yvar]], d0[[xvar]])
  lab <- sprintf("R = %.3f\nRMSE = %.1f\nMAE = %.1f\nME = %.1f",
                 st["Corr"], st["RMSE"], st["MAE"], st["ME"])
  xr <- range(d0[[xvar]]); yr <- range(d0[[yvar]])
  lab_x <- xr[1] + 0.02 * diff(xr); lab_y <- yr[2] - 0.02 * diff(yr)
  ggplot(d0, aes(x = .data[[xvar]], y = .data[[yvar]])) +
    geom_point(alpha = 0.55, size = 1.6, colour = "steelblue") +
    geom_abline(slope = 1, intercept = 0, linetype = "dashed", colour = "grey40") +
    geom_smooth(method = "lm", se = FALSE, colour = "red3", linewidth = 0.8, formula = y ~ x) +
    annotate("label", x = lab_x, y = lab_y, label = lab, hjust = 0, vjust = 1,
             size = 3.4, fill = "white", alpha = 0.85) +
    labs(x = paste(xvar, "population (×10⁴)"), y = paste(yvar, "population (×10⁴)"),
         title = paste("Scatter:", yvar, "vs", xvar)) +
    theme_bw()
}

# 误差直方图: (Y - X) 的分布。
#   - 黑色虚线 = 0(无误差); 红色线 = 平均误差
#   - 若分布整体偏左(红虚线<0), 说明 X 系统性高于 Y
plot_error_hist <- function(d0, xvar, yvar) {
  e <- d0[[yvar]] - d0[[xvar]]
  m <- mean(e)
  ggplot(data.frame(err = e), aes(x = err)) +
    geom_histogram(bins = 40, fill = "steelblue", colour = "white", alpha = 0.85) +
    geom_vline(xintercept = 0, linetype = "dashed", colour = "grey40") +
    geom_vline(xintercept = m, colour = "red3", linewidth = 0.9) +
    labs(x = paste("Error:", yvar, "-", xvar, "(×10⁴)"), y = "Frequency",
         title = paste("Error distribution:", yvar, "-", xvar, "| mean =", round(m, 1))) +
    theme_bw()
}

# 局部 R² 直方图: 每个城市局部回归的拟合优度。越靠右越好, 分布越宽空间异质性越强。
plot_r2_hist <- function(out, label) {
  ggplot(out, aes(x = Local_R2)) +
    geom_histogram(bins = 40, fill = "darkorange", colour = "white", alpha = 0.85) +
    labs(x = "Local R-squared", y = "Frequency",
         title = paste("Local R² distribution:", label)) +
    theme_bw()
}

# GWR 斜率系数直方图: 局部回归斜率(X 每变 1 单位, Y 变多少)。红虚线=1(无偏)。
plot_coef_hist <- function(out, label) {
  ggplot(out, aes(x = Coeff)) +
    geom_histogram(bins = 40, fill = "forestgreen", colour = "white", alpha = 0.85) +
    geom_vline(xintercept = 1, linetype = "dashed", colour = "red3", linewidth = 0.9) +
    labs(x = "GWR slope coefficient", y = "Frequency",
         title = paste("GWR coefficient:", label, "| dashed line = 1")) +
    theme_bw()
}

# 空间专题图(快速参考, 正式制图建议用 QGIS 精细化):
#   Local_R2 单色渐变(0~1, 越深拟合越好); LME 发散色带(蓝=负=X高于Y, 红=正=Y高于X)
plot_map_r2 <- function(out, label) {
  ggplot(out) +
    geom_sf(aes(fill = Local_R2), colour = NA) +
    scale_fill_gradient(low = "#FEE391", high = "#662506", limits = c(0, 1), name = "Local R²") +
    labs(title = paste("Local R² map:", label)) + theme_void()
}
plot_map_lme <- function(out, label) {
  ggplot(out) +
    geom_sf(aes(fill = LME), colour = NA) +
    scale_fill_gradient2(low = "#2166AC", mid = "#F7F7F7", high = "#B2182B",
                         midpoint = 0, name = "LME") +
    labs(title = paste("Local Mean Error map:", label)) + theme_void()
}


# 五、逐对分析: 计算各种值 + 输出图表 =========================================
for (p in PAIRS) {
  xvar <- p[["x"]]; yvar <- p[["y"]]
  tag   <- paste0(yvar, "_vs_", xvar)   # 文件名用
  label <- paste(yvar, "vs", xvar)      # 标题用
  cat("================ ", label, " ================\n", sep = "")

  ## 5.1 全局统计量
  gs <- global_stats(pop[[yvar]], pop[[xvar]])
  cat(sprintf("  全局: ME=%.2f  MAE=%.2f  MRE=%.3f  RMSE=%.2f  R=%.4f\n",
              gs["ME"], gs["MAE"], gs["MRE"], gs["RMSE"], gs["Corr"]))

  ## 5.2 带宽
  if (BW_MODE == "auto") {
    invisible(capture.output(
      bw <- bw.gwr(as.formula(paste(yvar, "~", xvar)), pop,
                   approach = "AIC", adaptive = ADAPTIVE, kernel = KERNEL)
    ))
  } else {
    bw <- BW
  }
  cat("  使用带宽 =", bw, if (ADAPTIVE) "(最近邻数)" else "(米)", "\n")

  ## 5.3 局部相关系数 gwss
  gss <- gwss(pop_sp, vars = c(yvar, xvar), adaptive = ADAPTIVE, bw = bw, kernel = KERNEL)
  corr_col <- grep("Corr", names(gss$SDF), value = TRUE)[1]

  ## 5.4 局部误差指标 gwmv (LME/LMAE/LMRE/LRMSE)
  invisible(capture.output(
    gv <- gwmv(pop, vars = c(yvar, xvar), adaptive = ADAPTIVE, bw = bw, kernel = KERNEL)
  ))
  lv <- st_drop_geometry(gv$SDF)

  ## 5.5 局部回归 gwr.basic (Y ~ X)
  gr <- gwr.basic(as.formula(paste(yvar, "~", xvar)), pop,
                  bw = bw, adaptive = ADAPTIVE, kernel = KERNEL)

  ## 5.6 汇总到输出 sf 对象
  out <- pop
  out$Corr     <- gss$SDF[[corr_col]]
  out$Coeff    <- gr$SDF[[xvar]]
  out$Local_R2 <- gr$SDF$Local_R2
  out$LME      <- lv[[paste0("LME_",  yvar, "_", xvar)]]
  out$LMAE     <- lv[[paste0("LMAE_", yvar, "_", xvar)]]
  out$LMRE     <- lv[[paste0("LMRE_", yvar, "_", xvar)]]
  out$LRMSE    <- lv[[paste0("LRMSE_", yvar, "_", xvar)]]

  ## 5.7 控制台输出局部结果摘要 (min / 中位数 / max)
  summ <- function(v) paste(round(min(v), 3), round(median(v), 3), round(max(v), 3), sep = " / ")
  cat("  局部相关系数 Corr : ", summ(out$Corr), "\n")
  cat("  GWR 斜率系数      : ", summ(out$Coeff), "\n")
  cat("  局部 R²           : ", summ(out$Local_R2), "\n")
  cat("  局部平均误差 LME  : ", summ(out$LME), "\n")
  cat("  局部绝对误差 LMAE : ", summ(out$LMAE), "\n")
  cat("  局部均方根误差LRMSE: ", summ(out$LRMSE), "\n\n")

  ## 5.8 写出 shapefile (先探测是否被 QGIS 占用, 被占用则跳过、绝不删一半)
  if (WRITE_SHP) {
    shp <- file.path(OUT_DIR, paste0("gwr_", tag, "_bw", bw, ".shp"))
    main_free <- if (!file.exists(shp)) TRUE else (unlink(shp) == 0)
    if (!main_free) {
      cat("  ! 跳过 shapefile(文件被 QGIS 占用, 请关闭后重跑):", basename(shp), "\n")
    } else {
      for (e in c(".shx", ".dbf", ".prj", ".cpg")) {
        f <- sub("\\.shp$", e, shp)
        if (file.exists(f)) try(unlink(f), silent = TRUE)
      }
      ok <- tryCatch({ st_write(out, shp, append = FALSE, quiet = TRUE, layer_options = "ENCODING=UTF-8"); TRUE },
                     error = function(e) FALSE)
      if (ok) cat("  已输出 shapefile:", shp, "\n")
      else cat("  ! shapefile 写出失败:", shp, "\n")
    }
  }

  ## 5.9 出图
  if (WRITE_PNG) {
    d0 <- st_drop_geometry(pop)
    if (PLOT_SCATTER)   save_fig(plot_scatter(d0, xvar, yvar),   paste0("fig_", tag, "_scatter.png"))
    if (PLOT_ERR_HIST)  save_fig(plot_error_hist(d0, xvar, yvar),paste0("fig_", tag, "_error_hist.png"))
    if (PLOT_R2_HIST)   save_fig(plot_r2_hist(out, label),       paste0("fig_", tag, "_localR2_hist.png"))
    if (PLOT_COEF_HIST) save_fig(plot_coef_hist(out, label),     paste0("fig_", tag, "_coef_hist.png"))
    if (PLOT_MAP) {
      save_fig(plot_map_r2(out, label),  paste0("fig_", tag, "_map_LocalR2.png"))
      save_fig(plot_map_lme(out, label), paste0("fig_", tag, "_map_LME.png"))
    }
    cat("\n")
  }
}


# 六、保存工作空间 ===========================================================
save.image(file = file.path(OUT_DIR, "GWR_2024_pop.RData"))
cat("分析完成, 结果与图表已保存至:", normalizePath(OUT_DIR), "\n")
