# 空间数据交叉验证工作台

面向 GIS 综合实习的多源空间数据验证项目。当前仓库以 Windows Qt 桌面客户端为主，支持属性数据、栅格数据和几何数据的登记、元数据检查、空间预处理、全局/局部差异分析和报告导出。

> 当前版本仍处于开发阶段。Python 和 R 中的部分算法适配器仍是占位实现；栅格分析链路已经接入真实的 `rasterio` 预处理和 R `terra` 脚本。

## 功能概览

- 数据管理：导入 CSV、XLSX/XLS、GeoTIFF、IMG、ASC、GeoPackage、Shapefile 和 GeoJSON。
- 元数据读取：识别字段、记录数、坐标系、空间范围、几何类型、预览记录和缺失值提示。
- 空间预处理：以参考栅格为目标网格，统一 CRS、分辨率、范围和单波段 GeoTIFF 输出。
- 属性/矢量分析：通过 Python 或 R 算法适配器执行任务，保留统一的 JSON 输入/输出接口。
- 栅格分析：调用 R `terra` 脚本，计算 ME、MAE、MRE、RMSE、Pearson 相关系数和局部窗口指标。
- 可视化：桌面端显示矢量几何、分析参数、指标卡、局部结果和任务状态。
- 导出：导出数据目录 CSV、分析报告 Markdown 以及栅格分析生成的 GeoTIFF/CSV/PNG 文件。

## 项目结构

```text
app/
├─ desktop_client/                         # Qt 桌面客户端
│  ├─ main.py                              # 程序入口
│  ├─ app/
│  │  ├─ main_window.py                    # 主窗口、导航、后台任务和 Rscript 设置
│  │  ├─ pages.py                          # 工作台、数据、预处理、分析、结果、设置页面
│  │  ├─ widgets.py                        # 地图画布和指标卡等控件
│  │  ├─ qt_compat.py                      # PySide6/PyQt6 兼容导入
│  │  └─ theme.py                          # Qt 样式
│  ├─ core/
│  │  ├─ models.py                         # 数据源、分析参数和结果模型
│  │  ├─ project.py                        # 项目数据源目录和运行时配置持久化
│  │  ├─ engine.py                         # 按后端分派分析任务
│  │  ├─ raster_processing.py              # rasterio 栅格对齐预处理
│  │  ├─ io/
│  │  │  ├─ readers.py                     # CSV/矢量/栅格元数据读取
│  │  │  ├─ data_registry.py               # 文件格式分类
│  │  │  └─ exporters.py                   # 报告和数据目录导出
│  │  └─ algorithms/
│  │     ├─ base.py                        # 算法运行器抽象接口
│  │     ├─ python_runner.py               # Python 子进程适配器
│  │     ├─ r_runner.py                    # Rscript 子进程适配器
│  │     ├─ raster_runner.py               # R/terra 栅格适配器
│  │     └─ stubs/                         # Python/R 占位算法
│  ├─ config/default_config.json           # 默认演示配置
│  ├─ requirements.txt                     # Python 依赖
│  ├─ run_client.ps1 / run_client.bat      # Windows 启动脚本
│  └─ SpatialValidationClient.spec         # PyInstaller 配置
├─ 属性数据算法/
│  ├─ #testcommand.r                       # 属性数据 GWR 批处理示例
│  └─ gwmv.r                               # 局部误差指标函数
└─ 栅格数据算法/
  ├─ desktop_raster_terra_analysis.R      # 桌面端调用的 R/terra 栅格脚本
  ├─ nightlight_terra_analysis.R          # 夜光数据独立分析脚本
  └─ gwmv.r                               # 栅格相关局部指标函数
```

## 快速启动桌面端

### 方式一：使用隔离虚拟环境（推荐）

在项目根目录执行：

```powershell
Set-Location .\desktop_client
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

如果 `py -3.13` 不可用，可以替换为本机已安装的 Python 3.10+：

```powershell
python -m venv .venv
```

启动脚本也可以直接运行：

```powershell
.\run_client.ps1
```

或双击 `run_client.bat`。如果项目目录已经存在 `.venv`，直接执行下面的命令即可：

```powershell
.\.venv\Scripts\python.exe main.py
```

### 方式二：使用已有 GIS/Conda 环境

启动脚本支持通过 `SPATIAL_VALIDATION_PYTHON` 指定 Python：

```powershell
$env:SPATIAL_VALIDATION_PYTHON = "D:\path\to\gdal\python.exe"
.\run_client.ps1
```

脚本会根据解释器目录设置 `PROJ_LIB` 和 `GDAL_DATA`。这对 `rasterio`、坐标转换和 GDAL 相关功能很重要。若使用普通虚拟环境，直接调用 `.venv\Scripts\python.exe main.py` 最稳定。

## 依赖

桌面端的必需依赖位于 `desktop_client/requirements.txt`：

- Python 3.10 或更高版本
- PyQt6
- rasterio

可选依赖：

- `openpyxl`：增强 XLSX 字段、样例和缺失值读取。
- R 及 `Rscript`：运行 R 占位算法和栅格 `terra` 分析。
- R 包 `jsonlite`：运行 `desktop_client/core/algorithms/stubs/gwr_placeholder.R`。
- R 包 `terra`：运行 `栅格数据算法/desktop_raster_terra_analysis.R`。
- R 包 `ggplot2`：栅格分析输出散点图；未安装时不影响核心统计和局部栅格输出。

如果使用 R 后端，请在桌面端“系统设置”中配置 `Rscript.exe` 路径。程序会把该路径传给普通 R 分析和栅格 `R / terra` 分析。

## 客户端使用流程

1. 启动桌面端，进入“数据管理”，导入至少一个或多个数据文件。
2. 检查每个数据源的格式、空间范围、CRS、记录数、字段和读取警告。
3. 处理栅格数据时，确保至少导入两个带 CRS 的单波段栅格。
4. 进入“预处理”，执行栅格统一。第一个栅格默认作为参考网格，也可以在代码层传入指定参考路径。
5. 进入“工作台”，选择 Python、R 或“栅格 R / terra”后端，设置变量、核函数、带宽和距离度量。
6. 点击“运行分析”，在“结果与报告”查看指标并导出报告。

普通属性/矢量分析使用占位 Python/R 脚本；选择“栅格 R / terra”时，客户端会优先使用预处理目录中的对齐栅格，并要求至少两个栅格数据源。

## 栅格处理链路

### 预处理

`desktop_client/core/raster_processing.py` 使用 `rasterio`：

- 以参考栅格的 CRS、仿射变换、宽高、范围和分辨率建立目标网格。
- 对所有栅格执行单波段检查和双线性重采样/投影。
- 将结果输出到 `desktop_client/.runtime/raster_preprocess/`。
- 在 `manifest.json` 中保存参考文件、对齐文件、目标网格和检查信息。

### 分析

`desktop_client/core/algorithms/raster_runner.py` 调用：

```text
栅格数据算法/desktop_raster_terra_analysis.R
```

R 脚本接收以下参数：

```text
Rscript desktop_raster_terra_analysis.R reference comparison output_dir [window_size] [scatter_max_points]
```

结果写入 `desktop_client/.runtime/raster_analysis/`，包括：

- `global_metrics.csv`
- `local_ME.tif`、`local_MAE.tif`、`local_MRE.tif`、`local_RMSE.tif`
- `local_correlation.tif`、`local_coefficient_no_intercept.tif`、`local_R2_no_intercept.tif`
- `reference_aligned.tif`、`comparison_aligned.tif`
- 安装 `ggplot2` 后生成的 `raster_scatter.png`

统一分析结果还会写入 `desktop_client/.runtime/analysis_result.json`。

## 算法接口

所有算法通过 `AlgorithmRunner.run(config, output_path)` 接入。调用方传入 JSON 配置，算法将 JSON 结果写入指定输出文件。结果至少应包含：

```json
{
 "status": "success",
 "engine": "算法名称",
 "metrics": {},
 "message": "处理结果说明",
 "local_values": []
}
```

替换真实算法时优先修改以下位置：

- Python 属性/模型算法：`desktop_client/core/algorithms/stubs/gwr_placeholder.py`
- R 属性/模型算法：`desktop_client/core/algorithms/stubs/gwr_placeholder.R`
- R 栅格算法：`栅格数据算法/desktop_raster_terra_analysis.R`
- 后端分派：`desktop_client/core/engine.py`
- 数据读取：`desktop_client/core/io/readers.py`
- 项目数据源持久化：`desktop_client/core/project.py`

## 独立 R 脚本

### 属性数据 GWR

`属性数据算法/#testcommand.r` 是一个批处理示例，默认读取 `data/2024_pop_result.shp`，并比较 `worldpop`、`ORNL_pop`、`pop2024` 等字段。它依赖 `sf`、`GWmodel`、`sp`、`ggplot2`、`RColorBrewer` 和 `scales`。

运行前请修改脚本顶部的数据路径、字段对、投影、带宽和输出目录：

```powershell
Rscript '.\属性数据算法\#testcommand.r'
```

### 夜光栅格分析

`栅格数据算法/nightlight_terra_analysis.R` 是独立的夜光数据分析脚本，需要在脚本顶部配置两个或多个 GeoTIFF 路径、输出目录、窗口大小和抽样上限。它依赖 R 包 `terra`，散点图还需要 `ggplot2`。

## 运行数据与清理

客户端运行过程中产生的配置、数据源清单、分析结果和栅格中间文件位于 `desktop_client/.runtime/`，该目录已加入 `.gitignore`，不会作为源码提交。

清理运行产物：

```powershell
Remove-Item -Recurse -Force .\desktop_client\.runtime
```

下次启动时，客户端会重新创建所需目录。

## 开发检查

修改 Python 代码后，可以先做无窗口导入和语法检查：

```powershell
Set-Location .\desktop_client
.\.venv\Scripts\python.exe -m compileall app core main.py
.\.venv\Scripts\python.exe -c "from app.main_window import SpatialValidationWindow; print('import ok')"
```

真实栅格分析还需要独立验证 R 环境：

```powershell
Rscript --version
Rscript -e "library(terra); cat('terra ok\\n')"
```

## 当前限制

- Python 和普通 R 后端中的 GWR 脚本目前是占位实现，返回演示指标；接入真实模型前不要将其结果用于正式研究结论。
- 栅格分析要求输入栅格存在 CRS、为单波段且至少有两个数据集。
- 当前 R/terra 栅格分析默认比较前两个栅格，并以预处理后的对齐文件作为输入。
- 根目录目前没有独立 Web 客户端；项目运行入口是 `desktop_client`。
