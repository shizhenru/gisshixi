# 空间数据交叉验证工作台

面向 GIS 综合实习的多源空间数据验证项目。当前仓库以 Windows Qt 桌面客户端为主，支持属性数据、栅格数据和几何数据的登记、元数据检查、空间预处理、全局/局部差异分析和报告导出。

> 当前版本仍处于开发阶段。Python 后端与「R 占位算法」仍是占位实现；属性数据 GWR 已接入真实 R 实现（`sf`/`GWmodel`），栅格分析链路已接入真实的 `rasterio` 预处理和 R `terra` 脚本。

## 功能概览

- 数据管理：导入 CSV、XLSX/XLS、GeoTIFF、IMG、ASC、GeoPackage、Shapefile 和 GeoJSON。
- 元数据读取：识别字段、记录数、坐标系、空间范围、几何类型、预览记录和缺失值提示。
- 空间预处理：以参考栅格为目标网格，统一 CRS、分辨率、范围和单波段 GeoTIFF 输出。
- 属性/矢量分析：通过 Python 或 R 算法适配器执行任务，保留统一的 JSON 输入/输出接口；「R 属性 GWR」后端为真实 GWR 实现。
- 栅格分析：调用 R `terra` 脚本，计算 ME、MAE、MRE、RMSE、Pearson 相关系数和局部窗口指标。
- 可视化：栅格散点图矩阵由 Python `matplotlib` 绘制；左下显示散点和回归线，右上显示两两指标，对角线显示直方图和密度曲线。
- 结果查看：结果与报告页提供全局/局部摘要、散点图矩阵、两两指标数据表格和可复现报告。
- 导出：导出数据目录 CSV、分析报告 Markdown 以及栅格分析生成的 GeoTIFF/CSV/PNG 文件。

## 功能栏目

界面采用「顶部导航 + 左侧数据选择 + 主内容」结构，五个栏目各司其职：

| 栏目 | 职责 |
| ------ | ------ |
| 工作台 | 设置 GWR 模型参数（因变量 Y / 自变量 X / 核函数 / 带宽 / 带宽策略 / 距离度量 / 算法后端）并运行，展示结果地图、散点图与属性表 |
| 数据管理 | 设定项目统一参数（坐标系 / 分辨率 / 研究区范围 / 数据格式），登记多源数据并做一致性检查（与统一参数不符的项标红） |
| 预处理 | 工具箱式界面：工具目录 + 参数面板 + 运行历史，已接入栅格对齐（统一 CRS / 分辨率 / 范围） |
| 空间分析 | 选择两幅栅格影像进行拉帘式左右对比（共享地图视图、可拖动分割线），并提供带宽区间探索（100–1000，步长 100） |
| 结果与报告 | 全局 / 局部模型摘要、散点图矩阵、两两指标数据表格与可复现的分析报告 |

## 项目结构

```text
desktop_client/                              # Qt 桌面客户端（项目运行入口）
├─ main.py                                   # 程序入口
├─ requirements.txt                          # Python 依赖
├─ run_client.ps1 / run_client.bat           # Windows 启动脚本
├─ SpatialValidationClient.spec              # PyInstaller 配置
├─ app/                                      # 界面层
│  ├─ main_window.py                         # 主窗口：导航 + 数据选择 + 页面堆栈 + 状态栏
│  ├─ qt_compat.py                           # PySide6/PyQt6 兼容导入
│  ├─ theme.py                               # Qt 样式
│  ├─ pages/                                 # 栏目页面，每个栏目一个子包
│  │  ├─ workbench/                          #   工作台
│  │  ├─ data/                               #   数据管理
│  │  ├─ preprocess/                         #   预处理
│  │  ├─ analysis/                           #   空间分析
│  │  ├─ results/                            #   结果与报告
│  │  └─ settings/                           #   系统设置
│  └─ widgets/                               # 共享 UI 组件
│     ├─ map_canvas.py                       #   地图画布（缩放/平移/复位）
│     ├─ raster_swipe_canvas.py               #   栅格拉帘对比画布（缩放/平移/分割线）
│     ├─ metric_card.py                      #   指标卡
│     ├─ panels.py                           #   面板/页头/布局工具
│     └─ data_select.py                      #   数据选择弹窗与左侧数据选择面板
└─ core/                                     # 业务逻辑层（不依赖 Qt）
   ├─ models.py                              # 数据源、分析参数和结果模型
   ├─ project.py                             # 项目数据源和运行时配置持久化
   ├─ engine.py                              # 按后端分派分析任务
   ├─ raster_processing.py                   # rasterio 栅格对齐预处理
  ├─ raster_plotting.py                      # matplotlib 栅格散点图矩阵
   ├─ algorithms/                            # 算法子系统
   │  ├─ base.py                             #   AlgorithmRunner 抽象基类
   │  ├─ python_runner.py                    #   Python 子进程适配器
   │  ├─ r_runner.py                         #   Rscript 子进程适配器
   │  ├─ raster_runner.py                    #   R/terra 栅格适配器
   │  └─ scripts/attribute/                  #   属性数据算法实现（JSON 进 → JSON 出）
   │     ├─ gwr_placeholder.py / .R          #   占位实现
   │     ├─ gwr_attribute.R                  #   真实 GWR（sf/GWmodel）
   │     └─ gwmv.r                           #   局部误差指标辅助函数
   └─ io/
      ├─ readers.py                          # CSV/矢量/栅格元数据与几何读取
      └─ exporters.py                        # 报告和数据目录导出

属性数据算法/                                 # 独立 R 脚本（GWR 批处理示例）
├─ #testcommand.r                            # 属性数据 GWR 两两比较批处理
└─ gwmv.r                                    # 局部误差指标函数

栅格数据算法/                                 # 独立 R 脚本（栅格分析）
├─ desktop_raster_terra_analysis.R           # 桌面端调用的 R/terra 栅格脚本
├─ nightlight_terra_analysis.R               # 夜光数据独立分析脚本
├─ generate_debug_raster_data.py              # 生成可重复的模拟栅格调试数据
├─ plot_debug_scatter_matrix.py               # 独立调试散点图矩阵样式
├─ debug_simulation/                          # 模拟像元、指标和图像产物
└─ gwmv.r                                    # 栅格相关局部指标函数
```

## 分层架构

整个项目分两层：

- **`app/`（界面层）**：负责「长什么样、怎么交互」，所有 Qt 组件、页面、样式都在这里。
- **`core/`（业务逻辑层）**：负责「数据和算法怎么算」，与界面无关，不 import 任何 Qt 组件。

`core/` 是整个后端，内部又分几块：

| 模块 | 作用 |
| ------ | ------ |
| `models.py` / `project.py` / `io/` | 数据：数据结构、数据源存储、数据读写 |
| `raster_processing.py` | 业务：栅格预处理 |
| `engine.py` | 调度：把「算法名」分发到对应的 runner + 脚本 |
| `algorithms/` | 算法：`*_runner.py` 是语言适配器（怎么执行），`scripts/` 是算法实现（算什么，按模式分类） |

一句话：`app/` 管界面与交互，`core/` 管数据与算法；`algorithms/scripts/` 只是其中「算法计算脚本」这一小块。

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
- numpy（栅格拉帘显示和像元拉伸）
- matplotlib（栅格散点图矩阵）

可选依赖：

- `openpyxl`：增强 XLSX 字段、样例和缺失值读取。
- R 及 `Rscript`：运行属性 GWR 算法和栅格 `terra` 分析。
- R 包 `jsonlite`：所有 R 算法适配器读取配置、写出 JSON 结果所需。
- R 包 `sf`、`GWmodel`、`sp`：运行属性数据 GWR（`scripts/attribute/gwr_attribute.R`）。
- R 包 `terra`：运行 `栅格数据算法/desktop_raster_terra_analysis.R`。
- R 包 `ggplot2`：仅独立 R 脚本需要时安装；桌面端栅格散点图矩阵由 Python `matplotlib` 绘制。

如果使用 R 后端，请在桌面端「系统设置」中配置 `Rscript.exe` 路径。程序会把该路径传给普通 R 分析和栅格 `R / terra` 分析。具体配置方法见下一节「配置 R 环境（Rscript）」。

## 配置 R 环境（Rscript）

### Rscript.exe 是什么

属性数据 GWR、栅格 `terra` 分析等算法用 R 语言编写，桌面客户端（Python/Qt）通过调用 `Rscript.exe` 来执行这些 `.R` 脚本。`Rscript.exe` 是 R 自带的命令行运行器——相当于用 `python.exe` 跑 `.py`、用 `Rscript.exe` 跑 `.R`，不需要打开 R 图形界面。

### 安装 R

若本机尚未安装 R，请到 [CRAN](https://cran.r-project.org/)（国内可选镜像 [清华 TUNA](https://mirrors.tuna.tsinghua.edu.cn/CRAN/)）下载 Windows 安装包并安装。Windows 下默认安装到 `C:\Program Files\R\R-x.y.z\`。

### 找到 Rscript.exe 路径

`Rscript.exe` 位于 R 安装目录的 `bin` 子目录，例如：

```text
C:\Program Files\R\R-4.5.3\bin\x64\Rscript.exe
```

优先选 `bin\x64\` 下的 64 位版本。也可以在 PowerShell 里用以下命令快速定位：

```powershell
where.exe Rscript
```

### 在客户端中配置

1. 打开客户端，点击右上角「⚙ 设置」。
2. 在「多语言运行环境」面板的「Rscript.exe 路径」中，点「浏览」选择上一步找到的 `Rscript.exe`，或直接粘贴路径。
3. 路径会自动保存，后续运行「R 属性 GWR」或「栅格 R / terra」都会使用该 R。

> 未配置时，程序会尝试从系统 PATH 中查找 `Rscript.exe`；若 PATH 里没有，则需手动配置。

### 安装所需 R 包

最省事的方式是用项目自带的 R 依赖清单（只装缺失的包，已装的自动跳过）：

```powershell
Set-Location .\desktop_client
Rscript requirements.R
```

或指定 Rscript 完整路径：

```powershell
& "C:\Program Files\R\R-4.5.3\bin\x64\Rscript.exe" ".\desktop_client\requirements.R"
```

也可以手动安装单个包，例如：

```powershell
& "C:\Program Files\R\R-4.5.3\bin\x64\Rscript.exe" -e "install.packages('terra', repos='https://cloud.r-project.org')"
```

R 包清单见 `desktop_client/requirements.R`（`requirements.txt` 中也有备注）。按算法需要安装：

| R 包 | 用途 |
| ------ | ------ |
| `jsonlite` | 所有 R 算法适配器读取配置、写出 JSON 结果（必需） |
| `sf`、`GWmodel`、`sp` | 属性数据 GWR（「R 属性 GWR」后端） |
| `terra` | 栅格分析（「栅格 R / terra」后端） |
| `ggplot2` | 独立 R 脚本输出散点图（可选） |

## 客户端使用流程

1. 启动桌面端，进入「数据管理」，导入至少一个或多个数据文件。
2. 检查每个数据源的格式、空间范围、CRS、记录数、字段和读取警告。
3. 处理栅格数据时，确保至少导入两个带 CRS 的单波段栅格。
4. 进入「预处理」，选择参考栅格，并在「本次处理栅格」列表中勾选需要统一的栅格（至少两个）；参考栅格会自动保留在选择列表中。
5. 点击运行栅格对齐。程序只处理本次勾选的数据，并把本次选择写入 manifest。
6. 进入「空间分析」，在「数据 A」和「数据 B」下拉框中选择本次已对齐的两幅栅格影像。
7. 在拉帘画布中拖动中央竖线：左侧显示数据 A，右侧显示数据 B；滚轮缩放、拖拽平移，点击「复位视图」恢复全图。
8. 进入「工作台」，选择 Python、R（含「R 属性 GWR」真实实现）或「栅格 R / terra」后端，设置变量、核函数、带宽和距离度量。
9. 点击「运行分析」，在「结果与报告」查看指标并导出报告。

普通属性/矢量分析中，Python 后端与「R 占位算法」仍是占位实现，返回演示指标；「R 属性 GWR」为真实 GWR 实现。选择「栅格 R / terra」时，客户端会优先使用预处理目录中的对齐栅格，并要求至少两个栅格数据源。

### 空间分析拉帘对比

空间分析页的拉帘功能仅负责两幅栅格的视觉对比，不计算差值、变化率或统计指标。两幅影像在显示前必须满足以下条件：

- 均为单波段栅格，并且可以由 `rasterio` 读取。
- CRS、宽度、高度、仿射变换和空间范围一致。
- 需要先在「预处理」页勾选目标栅格并运行「栅格对齐」，客户端只会使用 `desktop_client/.runtime/raster_preprocess/manifest.json` 中本次记录的对齐 GeoTIFF。
- 如果网格不一致，页面会提示先执行栅格对齐，不会直接进行像素位置对比。

画布会将有效像元拉伸到灰度显示，NoData 像元显示为透明；两幅影像使用各自的 2%–98% 有效像元范围进行显示拉伸。因此该功能适合观察空间位置和纹理差异，不应将当前灰度亮度直接解释为两个数据集之间的数值差异。

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
Rscript desktop_raster_terra_analysis.R config.json output.json
```

栅格分析与属性 GWR 使用相同的 JSON 任务接口。客户端会把参考栅格、对比栅格、局部窗口、重采样方法和输出选项写入 `config.json`，R 脚本将统一指标、局部样本和产物路径写入 `output.json`。栅格对齐优先由 Python `rasterio` 预处理完成，`terra` 负责统计与结果输出。

结果写入 `desktop_client/.runtime/raster_analysis/`，包括：

- `result.json`：全局摘要、局部摘要、两两比较指标和产物路径
- `raster_scatter_data.csv`：用于绘制散点图矩阵的抽样像元数据
- `raster_scatter_matrix.png`：Python `matplotlib` 生成的散点图矩阵
- `local_ME.tif`、`local_MAE.tif`、`local_MRE.tif`、`local_RMSE.tif`
- `local_correlation.tif`、`local_coefficient_no_intercept.tif`、`local_R2_no_intercept.tif`
- `reference_aligned.tif`、`comparison_aligned.tif`

统一分析结果还会写入 `desktop_client/.runtime/analysis_result.json`。

结果与报告页的“数据表格”标签会优先读取结果目录中的
`pairwise_global_metrics.csv` 或 `pairwise_metrics.csv`；如果没有 CSV，
则直接使用 `result.json` 中的 `pairwise_metrics` 生成同样的两两指标表格。

### 散点图矩阵调试

`栅格数据算法/` 下提供了一套独立的可视化调试数据和脚本，不依赖真实栅格即可调整样式：

```powershell
python .\栅格数据算法\generate_debug_raster_data.py
.\.venv\Scripts\python.exe .\栅格数据算法\plot_debug_scatter_matrix.py
```

产物位于 `栅格数据算法/debug_simulation/`：

- `scatter_data.csv`：模拟像元数据
- `pairwise_global_metrics.csv`：两两全局指标表
- `pairwise_metrics.csv`：JSON 结果结构对应的指标表
- `local_metrics.csv`：首对栅格的局部指标
- `result.json`：模拟客户端分析结果
- `scatter_matrix.png` / `scatter_matrix.pdf`：调试图像

矩阵样式为：左下三角显示散点和线性回归线，右上三角显示 Pearson's `r`、RMSE、MAE、ME 和有效样本数，对角线显示橙色直方图与密度曲线。调试完成后，客户端实际绘图实现位于 `desktop_client/core/raster_plotting.py`。

## 算法接口与添加指南

### 统一接口

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

算法分两层：

- **runner（语言适配器）**：负责「怎么执行」，与具体算法无关、可复用。在 `core/algorithms/` 根目录：`python_runner.py`（Python）、`r_runner.py`（Rscript）、`raster_runner.py`（R/terra）。
- **脚本（算法实现）**：负责「算什么」，按数据模式分类放在 `core/algorithms/scripts/` 下。

| 数据模式 | 脚本目录 | 当前算法 | 使用的 runner |
| --------- | --------- | --------- | -------------- |
| 属性数据 | `scripts/attribute/` | `gwr_placeholder.py` / `.R`（占位）、`gwr_attribute.R`（真实 GWR） | `python_runner` / `r_runner` |
| 栅格数据 | `scripts/raster/`（脚本暂在 `../栅格数据算法/`） | `desktop_raster_terra_analysis.R` | `raster_runner` |
| 几何数据 | `scripts/geometry/` | 外接矩形法几何交叉验证 | `python_runner` |

### 新增一个算法

1. 在对应模式的 `scripts/<模式>/` 下新建脚本（Python `.py` 或 R `.R`），约定「JSON 配置进 → JSON 结果出」。
2. 在 `core/engine.py` 的 `__init__` 里实例化一个 runner，指向新脚本。
3. 在 `engine.run()` 里按 `backend`（算法名）加一个分支，分发到对应 runner。
4. 在工作台「算法后端」下拉框里加对应选项（`app/pages/workbench/page.py`）。

### 同一模式下的多个算法（子分类）

- 直接在 `scripts/<模式>/` 下放多个脚本即可。例如属性模式下可放 `gwr.py`、`global_stats.py`、`ols.py`。
- `engine.py` 用 `backend` 字符串区分具体算法，把「模式 + 算法名」映射到「runner + 脚本」。
- 只有当「执行方式」不同（如需要 R/terra 环境、需要特殊参数处理）时才新增 runner；否则复用现有 `python_runner` / `r_runner`。

### 替换真实算法时优先修改的位置

- Python 属性/模型算法：`desktop_client/core/algorithms/scripts/attribute/gwr_placeholder.py`（占位）
- R 属性/模型算法（真实 GWR）：`desktop_client/core/algorithms/scripts/attribute/gwr_attribute.R`
  - 局部误差指标辅助函数：`desktop_client/core/algorithms/scripts/attribute/gwmv.r`
  - 该脚本是对 `属性数据算法/#testcommand.r` 的参数化封装，由「R 属性 GWR」后端调用。
- R 栅格算法：`栅格数据算法/desktop_raster_terra_analysis.R`
- 后端分派：`desktop_client/core/engine.py`
- 数据读取：`desktop_client/core/io/readers.py`
- 项目数据源持久化：`desktop_client/core/project.py`

## 开发指南

本项目按「栏目」划分代码，请遵循以下规则，保持框架整洁、可并行开发。

### 目录职责

- `app/pages/<栏目>/`：每个栏目一个子包，只负责该栏目的界面。
- `app/widgets/`：跨栏目共享的 UI 组件（地图、指标卡、面板工具、数据选择）。
- `app/qt_compat.py`：PySide6 / PyQt6 兼容层，**统一从这里导入 Qt 组件**，不要直接 `import PyQt6`。
- `app/theme.py`：全局样式表。
- `core/`：与界面无关的业务逻辑（数据模型、存储、算法、数据读取）。

### 栏目独立性

- 每个栏目页面是自包含的 `QWidget`，只通过 `ProjectStore`（数据）和 `Qt Signal`（事件）与外部通信。
- 栏目之间需要联动时，在 `main_window.py` 里做信号接线，而不是直接调用对方的类或方法。

### core 层文件说明

| 文件 | 职责 | 什么时候用 |
| ------ | ------ | ----------- |
| `models.py` | 数据模型：`DataSource` / `AnalysisParameters` / `AnalysisResult` | 描述数据源、传分析参数、接收结果 |
| `project.py` | `ProjectStore`：数据源增删与持久化（`.runtime/sources.json`） | 导入 / 删除数据、拿数据源列表 |
| `engine.py` | `AnalysisEngine`：按 backend 分发给 Python / R / 栅格算法 | 运行分析任务 |
| `raster_processing.py` | `RasterPreprocessor`：栅格对齐（CRS / 分辨率 / 范围） | 预处理「栅格对齐」工具 |
| `algorithms/` | 算法适配器：`base.py` 抽象基类 + Python / R / R-terra runner + `scripts/` 脚本 | 接入真实算法时 |
| `io/` | `readers.py` 读元数据 / SHP 几何、`exporters.py` 导出报告 / 清单 | 新增数据格式、导出结果 |

界面用数据时 `from core.project import ProjectStore`、用模型时 `from core.models import ...`、跑算法时 `from core.engine import AnalysisEngine`。

### 新增功能的位置

- 新增算法：见「算法接口与添加指南」小节。
- 新增预处理工具：在 `app/pages/preprocess/page.py` 的 `TOOLS` 列表登记工具，并在参数面板实现其参数。
- 新增数据格式：在 `core/io/readers.py` 的 `read_metadata` 增加分支。
- 新增共享组件：放 `app/widgets/`，不要在各栏目里复制粘贴。

### 命名与规范

- 页面类命名为 `XxxPage`，子包入口统一为 `from .page import XxxPage`。
- 页面通过 `statusMessage`、`runRequested` 等信号向主窗口发消息，由主窗口统一处理状态栏与跨页联动。
- 删除或移植代码时，保证没有残留未使用的代码、导入或文件。

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

## 几何数据交叉验证

工作台的“外接矩形法几何交叉验证”支持选择两个 Shapefile，分别配置类别字段，并通过“A 类别值 ↔ B 类别值 ↔ 显示名称”映射表处理两套数据编码不一致的情况。算法按类别生成轴对齐外接矩形候选对，在 0.1–0.9 九个 IoU 阈值下进行一对一贪心匹配，再使用修复后的原始面计算面 IoU、质心距离、面积误差、周长误差和地理加权指标。

运行结果默认保存到 `几何数据算法/results/run_年月日_时分秒/`，包括 `tables/`、`figures/` 和 `report/`。原始 SHP 不会被修改；空几何会被排除，无效几何使用 `make_valid` 在内存中修复，数量记录在 `tables/run_metadata.json`。

百万级 SHP 的八类全量分析属于重计算任务。当前测试数据在 10,000 m² 面积阈值下约需 10 分钟、峰值内存约 2 GB；建议先单类别试算确认映射和参数，再执行全部类别。运行期间客户端使用后台线程并显示进度条，请勿重复提交任务或直接关闭客户端。

## 当前限制

- Python 后端与「R 占位算法」中的 GWR 脚本目前是占位实现，返回演示指标；接入真实模型前不要将其结果用于正式研究结论。属性数据 GWR 已由「R 属性 GWR」后端提供真实实现。
- 栅格分析要求输入栅格存在 CRS、为单波段且至少有两个数据集。
- 空间分析拉帘要求两幅栅格具有相同 CRS、尺寸、仿射变换和空间范围；该功能当前只提供视觉对比，不生成差值栅格。
- 当前 R/terra 栅格分析默认比较前两个栅格，并以预处理后的对齐文件作为输入。
- 根目录目前没有独立 Web 客户端；项目运行入口是 `desktop_client`。
