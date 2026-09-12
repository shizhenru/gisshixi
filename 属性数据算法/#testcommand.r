# ============================================================================
#  2024 多源人口数据 · 地理加权回归(GWR)验证分析
# ============================================================================
#  目的 : 以统计年鉴人口(pop2024)为"参考真值", 用 GWR 方法逐城市验证
#         WorldPop 与 ORNL LandScan 两套遥感人口数据的精度及其空间异质性。
#  方法 : (1) 全局验证统计量 ME/MAE/MRE/RMSE/相关系数
#         (2) 局部验证: 局部相关系数(gwss)、局部误差指标(gwmv)、局部回归(gwr.basic)
#  运行 : RStudio 里 source 本文件, 或命令行 Rscript "#testcommand.r"
#  依赖 : sf, GWmodel, sp, ggplot2, RColorBrewer, scales
# ============================================================================


# 〇、可调参数区 (PARAMETERS) ===============================================
# 只需要改这里的参数即可重新出结果, 下面的代码无需改动。

## ---- 数据输入 ----
SHP_PATH <- "data/2024_pop_result.shp"   # 输入 shapefile 路径
REF_VAR  <- "pop2024"                    # 参考真值字段名(统计年鉴人口)
SAT_VARS <- c("worldpop", "ORNL_pop")    # 待验证的卫星人口数据字段名(可 1~多个)
DROP_NA  <- TRUE                         # TRUE=剔除参考值缺失的行(台湾/港澳/保护区/农场等)

## ---- 空间设置 ----
# 投影到 China Albers 等积圆锥投影(单位: 米), 保证 GWR 的距离度量正确。
# 若你的数据本来就是投影坐标, 可把这里换成对应 EPSG, 或保持 WGS84 并改用 longlat 距离。
PROJ_CRS <- "+proj=aea +lat_1=25 +lat_2=47 +lat_0=0 +lon_0=105 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"

## ---- GWR 核心设置 ----
KERNEL   <- "bisquare"   # 核函数: bisquare / gaussian / exponential / tricube / boxcar
ADAPTIVE <- TRUE         # TRUE =自适应带宽(用"最近邻个数"表示); FALSE =固定距离带宽(用"米"表示)
BW_MODE  <- "fixed"      # "fixed"=使用下面 BW 的固定值; "auto"=按 AIC 自动求最优带宽
BW       <- 25           # 仅 BW_MODE="fixed" 时生效。ADAPTIVE=TRUE 时是"最近邻个数";
                         # ADAPTIVE=FALSE 时是"固定距离(米)", 例如 400000 = 400km
#   ★ 带宽含义: 每个城市的局部回归只用它最近的 BW 个邻居, 越近权重越大(核函数加权)。
#   ★ 带宽越大 → 越平滑(偏全局, 分层设色呈大尺度渐变);
#     带宽越小 → 越局部(分层设色更"碎", 城市间区分度更大), 但太小会过拟合噪声。
#   ★ 经验: 25 是区分度与稳定性的较好平衡点(局部R2极差 0.294, Moran's I 0.813)。
#     若想看"统计最优"版本, 设 BW_MODE="auto"(worldpop 会得到约 73, 结果更平滑)。

## ---- 输出设置 ----
OUT_DIR   <- "results"    # 输出目录(自动创建)
WRITE_SHP <- TRUE         # TRUE=写出结果 shapefile(可在 QGIS 里制图)
WRITE_PNG <- TRUE         # TRUE=画出图表 PNG
FIG_W     <- 8            # 图宽(英寸)
FIG_H     <- 6            # 图高(英寸)
FIG_DPI   <- 300          # 图分辨率(dpi)

## ---- 图表开关(哪些图要画) ----
PLOT_SCATTER   <- TRUE    # 散点图: 参考真值 vs 卫星值(含 1:1 参考线与回归线)
PLOT_ERR_HIST  <- TRUE    # 误差直方图: (参考 - 卫星) 的分布, 检验有无系统性偏差
PLOT_R2_HIST   <- TRUE    # 局部 R² 直方图: 逐城市局部拟合优度的分布
PLOT_COEF_HIST <- TRUE    # GWR 斜率系数直方图: 局部系数的空间变异
PLOT_MAP       <- TRUE    # 空间专题图: 局部 R² 与局部平均误差 LME 的分布图


# 一、加载依赖包 =============================================================
suppressPackageStartupMessages({
  library(sf)          # 空间矢量数据读写
  library(GWmodel)     # 地理加权回归
  library(sp)          # GWmodel 的底层空间对象
  library(ggplot2)     # 绘图
  library(RColorBrewer)
  library(scales)
})
sf_use_s2(FALSE)       # 关闭球面几何, 避免经纬度几何运算报错
source("gwmv.r")       # 局部验证指标函数(自定义)

dir.create(OUT_DIR, showWarnings = FALSE)


# 二、读取与清洗数据 =========================================================
pop <- st_read(SHP_PATH, quiet = TRUE)
# 说明: 该输入文件字段顺序为 name, gb, Province_n(截断), X2024_pop, worldpop, ORNL_pop, geometry。
#       这里统一重命名为易读的字段名(2024_pop 被 sf 加了 X 前缀, Province_name 被 DBF 截断)。
names(pop) <- c("name", "gb", "Province", REF_VAR, SAT_VARS, "geometry")

if (DROP_NA) {
  n0 <- nrow(pop)
  pop <- pop[!is.na(pop[[REF_VAR]]), ]
  cat("== 数据清洗 ==\n")
  cat("剔除参考值缺失的记录:", n0 - nrow(pop), "条(台湾/港澳/自然保护区/农场等)\n")
  cat("有效样本数(地级行政区):", nrow(pop), "\n\n")
}


# 三、投影 ===================================================================
pop <- st_transform(pop, PROJ_CRS)
pop_sp <- as(pop, "Spatial")     # gwss 只接受 Spatial*/data.frame 对象


# 四、全局验证统计量 =========================================================
# 计算"参考值 - 卫星值"的全局误差指标。
#  ME   = mean(参考 - 卫星): 平均误差(偏置), 负值=卫星高估统计人口
#  MAE  = mean(|参考 - 卫星|): 平均绝对误差
#  MRE  = mean(|参考 - 卫星| / 卫星): 平均相对误差(以卫星值为分母)
#  RMSE = sqrt(mean((参考 - 卫星)^2)): 均方根误差(对大误差更敏感)
#  Corr = 皮尔逊相关系数: 两套数据整体一致性
global_stats <- function(ref, sat) {
  d <- ref - sat
  c(ME = mean(d), MAE = mean(abs(d)), MRE = mean(abs(d) / sat),
    RMSE = sqrt(mean(d^2)), Corr = cor(ref, sat))
}
cat("== 全局验证统计量 (参考", REF_VAR, ", 单位: 万人) ==\n")
gstat <- t(sapply(SAT_VARS, function(s) global_stats(pop[[REF_VAR]], pop[[s]])))
print(round(gstat, 4))
cat("\n")


# 五、绘图辅助函数 ===========================================================
# 所有图的坐标轴用英文(避免中文字体问题); 需要中文可在此把文字改掉。

save_fig <- function(gg, fname) {
  if (!WRITE_PNG) return(invisible(NULL))
  path <- file.path(OUT_DIR, fname)
  if (file.exists(path)) try(unlink(path), silent = TRUE)   # 先删旧图, 避免被图片查看器/缩略图占用
  ok <- tryCatch({
    ggsave(path, plot = gg, width = FIG_W, height = FIG_H, dpi = FIG_DPI)
    TRUE
  }, error = function(e) FALSE)
  if (ok) cat("  已出图:", path, "\n")
  else cat("  ! 出图失败(文件可能被占用, 请关闭后重跑):", path, "\n")
  invisible(ok)
}

# 散点图: 每个城市一个点, x=卫星值, y=参考值。
#   - 黑色虚线 = 1:1 参考线(点若落在线上说明完全一致)
#   - 红色线 = 最小二乘回归线(整体趋势)
#   - 左上角标注 R/RMSE/MAE/ME
plot_scatter <- function(d0, ref, sat) {
  st <- global_stats(d0[[ref]], d0[[sat]])
  lab <- sprintf("R = %.3f\nRMSE = %.1f\nMAE = %.1f\nME = %.1f",
                 st["Corr"], st["RMSE"], st["MAE"], st["ME"])
  xr <- range(d0[[sat]]); yr <- range(d0[[ref]])
  lab_x <- xr[1] + 0.02 * diff(xr); lab_y <- yr[2] - 0.02 * diff(yr)
  ggplot(d0, aes(x = .data[[sat]], y = .data[[ref]])) +
    geom_point(alpha = 0.55, size = 1.6, colour = "steelblue") +
    geom_abline(slope = 1, intercept = 0, linetype = "dashed", colour = "grey40") +
    geom_smooth(method = "lm", se = FALSE, colour = "red3", linewidth = 0.8, formula = y ~ x) +
    annotate("label", x = lab_x, y = lab_y, label = lab, hjust = 0, vjust = 1,
             size = 3.4, fill = "white", alpha = 0.85) +
    labs(x = paste(sat, "population (×10⁴)"), y = paste(ref, "population (×10⁴)"),
         title = paste("Scatter:", ref, "vs", sat)) +
    theme_bw()
}

# 误差直方图: (参考 - 卫星) 的分布。
#   - 黑色虚线 = 0(无误差); 红色线 = 平均误差(偏置)
#   - 若分布整体偏左(红虚线<0), 说明卫星系统性高估人口
plot_error_hist <- function(d0, ref, sat) {
  e <- d0[[ref]] - d0[[sat]]
  m <- mean(e)
  ggplot(data.frame(err = e), aes(x = err)) +
    geom_histogram(bins = 40, fill = "steelblue", colour = "white", alpha = 0.85) +
    geom_vline(xintercept = 0, linetype = "dashed", colour = "grey40") +
    geom_vline(xintercept = m, colour = "red3", linewidth = 0.9) +
    labs(x = paste("Error:", ref, "-", sat, "(×10⁴)"), y = "Frequency",
         title = paste("Error distribution:", sat, "| mean =", round(m, 1))) +
    theme_bw()
}

# 局部 R² 直方图: 每个城市局部回归的拟合优度。整体越靠右(接近1)说明拟合越好,
# 分布越宽说明空间异质性越强(有的地方拟合好、有的地方差)。
plot_r2_hist <- function(out, sat) {
  ggplot(out, aes(x = Local_R2)) +
    geom_histogram(bins = 40, fill = "darkorange", colour = "white", alpha = 0.85) +
    labs(x = "Local R-squared", y = "Frequency",
         title = paste("Local R² distribution:", sat)) +
    theme_bw()
}

# GWR 斜率系数直方图: 局部回归的斜率(卫星值每变 1 单位, 参考值变化多少)。
#   - 红色虚线 = 1(无偏); 分布越分散说明两套数据的关系随空间变化越大。
plot_coef_hist <- function(out, sat) {
  ggplot(out, aes(x = Coeff)) +
    geom_histogram(bins = 40, fill = "forestgreen", colour = "white", alpha = 0.85) +
    geom_vline(xintercept = 1, linetype = "dashed", colour = "red3", linewidth = 0.9) +
    labs(x = "GWR slope coefficient", y = "Frequency",
         title = paste("GWR coefficient distribution:", sat, "| dashed line = 1")) +
    theme_bw()
}

# 空间专题图(快速参考, 正式制图建议用 QGIS 精细化):
#   - Local_R2 用单色渐变(0~1, 越深拟合越好)
#   - LME 用发散色带(蓝=负=卫星高估, 红=正=卫星低估, 白=0)
plot_map_r2 <- function(out, sat) {
  ggplot(out) +
    geom_sf(aes(fill = Local_R2), colour = NA) +
    scale_fill_gradient(low = "#FEE391", high = "#662506", limits = c(0, 1), name = "Local R²") +
    labs(title = paste("Local R² map:", sat)) + theme_void()
}
plot_map_lme <- function(out, sat) {
  ggplot(out) +
    geom_sf(aes(fill = LME), colour = NA) +
    scale_fill_gradient2(low = "#2166AC", mid = "#F7F7F7", high = "#B2182B",
                         midpoint = 0, name = "LME") +
    labs(title = paste("Local Mean Error map:", sat)) + theme_void()
}


# 六、逐数据集: 局部验证 + GWR + 出图 =========================================
models <- list()
for (sat in SAT_VARS) {

  cat("================ ", sat, " ================\n", sep = "")

  ## 6.1 带宽选择
  if (BW_MODE == "auto") {
    invisible(capture.output(
      bw <- bw.gwr(as.formula(paste(REF_VAR, "~", sat)), pop,
                   approach = "AIC", adaptive = ADAPTIVE, kernel = KERNEL)
    ))
    cat("自动带宽(AIC) =", bw, "\n")
  } else {
    bw <- BW
  }
  cat("使用带宽 =", bw, if (ADAPTIVE) "(最近邻数)" else "(米)", "\n")

  ## 6.2 局部相关系数 gwss (相关系数 = 参考值与卫星值在局部邻域内的相关强度)
  gs <- gwss(pop_sp, vars = c(REF_VAR, sat), adaptive = ADAPTIVE, bw = bw, kernel = KERNEL)
  corr_col <- grep("Corr", names(gs$SDF), value = TRUE)[1]

  ## 6.3 局部验证指标 gwmv (LME/LMAE/LMRE/LRMSE)
  invisible(capture.output(
    gv <- gwmv(pop, vars = c(REF_VAR, sat), adaptive = ADAPTIVE, bw = bw, kernel = KERNEL)
  ))
  lv <- st_drop_geometry(gv$SDF)

  ## 6.4 局部回归 gwr.basic (参考 ~ 卫星)
  gr <- gwr.basic(as.formula(paste(REF_VAR, "~", sat)), pop,
                  bw = bw, adaptive = ADAPTIVE, kernel = KERNEL)

  ## 6.5 汇总到输出 sf 对象
  out <- pop
  out$Corr     <- gs$SDF[[corr_col]]
  out$Coeff    <- gr$SDF[[sat]]
  out$Local_R2 <- gr$SDF$Local_R2
  out$LME      <- lv[[paste0("LME_",  REF_VAR, "_", sat)]]
  out$LMAE     <- lv[[paste0("LMAE_", REF_VAR, "_", sat)]]
  out$LMRE     <- lv[[paste0("LMRE_", REF_VAR, "_", sat)]]
  out$LRMSE    <- lv[[paste0("LRMSE_", REF_VAR, "_", sat)]]
  models[[sat]] <- out

  ## 6.6 控制台输出局部结果摘要 (min / 中位数 / max)
  summ <- function(v) paste(round(min(v), 3), round(median(v), 3), round(max(v), 3), sep = " / ")
  cat("  局部相关系数 Corr : ", summ(out$Corr), "\n")
  cat("  GWR 斜率系数      : ", summ(out$Coeff), "\n")
  cat("  局部 R²           : ", summ(out$Local_R2), "\n")
  cat("  局部平均误差 LME  : ", summ(out$LME), "\n")
  cat("  局部绝对误差 LMAE : ", summ(out$LMAE), "\n")
  cat("  局部均方根误差LRMSE: ", summ(out$LRMSE), "\n\n")

  ## 6.7 写出 shapefile (若同名文件正被 QGIS 打开, 会锁定导致写失败; 这里先删旧文件并容错)
  if (WRITE_SHP) {
    shp <- file.path(OUT_DIR, paste0("gwr_", sat, "_bw", bw, ".shp"))
    for (e in c(".shp", ".shx", ".dbf", ".prj", ".cpg")) {
      f <- sub("\\.shp$", e, shp)
      if (file.exists(f)) try(unlink(f), silent = TRUE)
    }
    ok <- tryCatch({
      st_write(out, shp, append = FALSE, quiet = TRUE, layer_options = "ENCODING=UTF-8")
      TRUE
    }, error = function(e) FALSE)
    if (ok) cat("  已输出 shapefile:", shp, "\n")
    else cat("  ! shapefile 写出失败(多半是 QGIS 正打开同名文件, 请关闭后再运行)\n")
  }

  ## 6.8 出图
  if (WRITE_PNG) {
    d0 <- st_drop_geometry(pop)
    if (PLOT_SCATTER)   save_fig(plot_scatter(d0, REF_VAR, sat),   paste0("fig_", sat, "_scatter.png"))
    if (PLOT_ERR_HIST)  save_fig(plot_error_hist(d0, REF_VAR, sat),paste0("fig_", sat, "_error_hist.png"))
    if (PLOT_R2_HIST)   save_fig(plot_r2_hist(out, sat),           paste0("fig_", sat, "_localR2_hist.png"))
    if (PLOT_COEF_HIST) save_fig(plot_coef_hist(out, sat),         paste0("fig_", sat, "_coef_hist.png"))
    if (PLOT_MAP) {
      save_fig(plot_map_r2(out, sat),  paste0("fig_", sat, "_map_LocalR2.png"))
      save_fig(plot_map_lme(out, sat), paste0("fig_", sat, "_map_LME.png"))
    }
    cat("\n")
  }
}


# 七、保存工作空间 ===========================================================
save.image(file = file.path(OUT_DIR, "GWR_2024_pop.RData"))
cat("分析完成, 结果与图表已保存至:", normalizePath(OUT_DIR), "\n")
