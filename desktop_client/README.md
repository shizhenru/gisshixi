# 空间数据交叉验证工作台

基于 PyQt 的 Windows 桌面客户端，用于多源空间数据的一致性验证与地理加权回归（GWR）分析。界面采用「顶部导航 + 左侧数据选择 + 主内容」结构，五个栏目各司其职。

## 功能栏目

| 栏目 | 职责 |
|------|------|
| 工作台 | 设置 GWR 模型参数（因变量 Y / 自变量 X / 核函数 / 带宽 / 带宽策略 / 距离度量 / 算法后端）并运行，展示结果地图、散点图与属性表 |
| 数据管理 | 设定项目统一参数（坐标系 / 分辨率 / 研究区范围 / 数据格式），登记多源数据并做一致性检查（与统一参数不符的项标红） |
| 预处理 | 工具箱式界面：工具目录 + 参数面板 + 运行历史，已接入栅格对齐（统一 CRS / 分辨率 / 范围） |
| 空间分析 | 拉帘式对比两个数据源 + 带宽区间探索（100–1000，步长 100） |
| 结果与报告 | 全局 / 局部模型摘要、图表与可复现的分析报告 |

## 目录结构

```text
desktop_client/
├─ main.py                          # 程序入口
├─ requirements.txt
├─ app/
│  ├─ main_window.py                # 主窗口：顶部导航 + 左侧数据选择 + 页面堆栈 + 状态栏
│  ├─ pages/                        # 栏目页面，每个一个独立子包
│  │  ├─ workbench/                 #   工作台
│  │  ├─ data/                      #   数据管理
│  │  ├─ preprocess/                #   预处理
│  │  ├─ analysis/                  #   空间分析
│  │  ├─ results/                   #   结果与报告
│  │  └─ settings/                  #   系统设置
│  ├─ widgets/                      # 共享 UI 组件
│  │  ├─ map_canvas.py              #   地图画布（缩放 / 平移 / 复位）
│  │  ├─ metric_card.py             #   指标卡
│  │  ├─ panels.py                  #   面板 / 页头 / 布局工具
│  │  └─ data_select.py             #   数据选择弹窗与左侧数据选择面板
│  ├─ qt_compat.py                  # PySide6 / PyQt6 兼容层
│  └─ theme.py                      # Qt 样式表
└─ core/
   ├─ models.py                     # 数据模型与结果模型
   ├─ project.py                    # 项目与数据源持久化
   ├─ engine.py                     # 调度中心：把「算法名」分发到 runner + 脚本
   ├─ raster_processing.py          # 栅格预处理（对齐 CRS / 分辨率 / 范围）
   ├─ algorithms/                   # 算法子系统
   │  ├─ base.py                    #   AlgorithmRunner 抽象基类
   │  ├─ python_runner.py           #   Python 语言适配器
   │  ├─ r_runner.py                #   Rscript 语言适配器
   │  ├─ raster_runner.py           #   R/terra 语言适配器
   │  └─ scripts/                   #   算法实现脚本，按数据模式分类
   │     ├─ attribute/              #     属性数据算法（GWR）
   │     ├─ raster/                 #     栅格数据算法
   │     └─ geometry/               #     几何数据算法
   └─ io/                           # 数据读取与导出
```

## 分层架构

整个项目分两层：

- **`app/`（界面层）**：负责「长什么样、怎么交互」。所有 Qt 组件、页面、样式都在这里。
- **`core/`（业务逻辑层）**：负责「数据和算法怎么算」，与界面无关，不 import 任何 Qt 组件。

`core/` 不是「算法目录」，而是整个后端，内部又分几块：

| 模块 | 作用 |
|------|------|
| `models.py` / `project.py` / `io/` | 数据：数据结构、数据源存储、数据读写 |
| `raster_processing.py` | 业务：栅格预处理 |
| `engine.py` | 调度：把「算法名」分发到对应的 runner + 脚本 |
| `algorithms/` | 算法：`*_runner.py` 是语言适配器（怎么执行），`scripts/` 是算法实现（算什么，按模式分类） |

一句话：`core/` 是整个后端，`algorithms/scripts/` 只是其中「算法计算脚本」这一小块。

## 运行

```powershell
python -m pip install -r requirements.txt
python main.py
```

依赖清单见 `requirements.txt`（PyQt6 必需，rasterio 用于栅格预处理；数据读取为零依赖渐进式，装 openpyxl 后可读 XLSX 字段）。

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

`core/` 负责「数据和算法怎么算」，与界面无关。各文件职责与使用时机：

| 文件 | 职责 | 什么时候用 |
|------|------|-----------|
| `models.py` | 数据模型：`DataSource` / `AnalysisParameters` / `AnalysisResult` | 描述数据源、传分析参数、接收结果 |
| `project.py` | `ProjectStore`：数据源增删与持久化（`.runtime/sources.json`） | 导入 / 删除数据、拿数据源列表 |
| `engine.py` | `AnalysisEngine`：按 backend 分发给 Python / R / 栅格算法 | 运行分析任务 |
| `raster_processing.py` | `RasterPreprocessor`：栅格对齐（CRS / 分辨率 / 范围） | 预处理「栅格对齐」工具 |
| `algorithms/` | 算法适配器：`base.py` 抽象基类 + Python / R / R-terra runner + `stubs/` 占位脚本 | 接入真实算法时 |
| `io/` | `readers.py` 读元数据 / SHP 几何、`exporters.py` 导出报告 / 清单 | 新增数据格式、导出结果 |

一句话：`app/` 管界面与交互，`core/` 管数据与算法。界面用数据时 `from core.project import ProjectStore`、用模型时 `from core.models import ...`、跑算法时 `from core.engine import AnalysisEngine`。

### 算法添加指南

本项目有三种数据模式的计算算法：**属性数据、栅格数据、几何数据**。算法分两层：

- **runner（语言适配器）**：负责「怎么执行」，与具体算法无关、可复用。在 `core/algorithms/` 根目录：`python_runner.py`（Python）、`r_runner.py`（Rscript）、`raster_runner.py`（R/terra）。
- **脚本（算法实现）**：负责「算什么」，按数据模式分类放在 `core/algorithms/scripts/` 下。

| 数据模式 | 脚本目录 | 当前算法 | 使用的 runner |
|---------|---------|---------|--------------|
| 属性数据 | `scripts/attribute/` | `gwr_placeholder.py` / `.R`（GWR） | `python_runner` / `r_runner` |
| 栅格数据 | `scripts/raster/`（脚本暂在 `../栅格数据算法/`） | `desktop_raster_terra_analysis.R` | `raster_runner` |
| 几何数据 | `scripts/geometry/`（待新增） | 未实现 | 复用或新增 runner |

**新增一个算法的步骤：**

1. 在对应模式的 `scripts/<模式>/` 下新建脚本（Python `.py` 或 R `.R`），约定「JSON 配置进 → JSON 结果出」。
2. 在 `core/engine.py` 的 `__init__` 里实例化一个 runner，指向新脚本。
3. 在 `engine.run()` 里按 `backend`（算法名）加一个分支，分发到对应 runner。
4. 在工作台「算法后端」下拉框里加对应选项（`app/pages/workbench/page.py`）。

**同一模式下的多个算法（子分类）：**

- 直接在 `scripts/<模式>/` 下放多个脚本即可。例如属性模式下可放 `gwr.py`、`global_stats.py`、`ols.py`。
- `engine.py` 用 `backend` 字符串区分具体算法，把「模式 + 算法名」映射到「runner + 脚本」。
- 只有当「执行方式」不同（如需要 R/terra 环境、需要特殊参数处理）时才新增 runner；否则复用现有 `python_runner` / `r_runner`。

### 新增功能的位置

- 新增算法：见「算法添加指南」小节。
- 新增预处理工具：在 `app/pages/preprocess/page.py` 的 `TOOLS` 列表登记工具，并在参数面板实现其参数。
- 新增数据格式：在 `core/io/readers.py` 的 `read_metadata` 增加分支。
- 新增共享组件：放 `app/widgets/`，不要在各栏目里复制粘贴。

### 命名与规范

- 页面类命名为 `XxxPage`，子包入口统一为 `from .page import XxxPage`。
- 页面通过 `statusMessage`、`runRequested` 等信号向主窗口发消息，由主窗口统一处理状态栏与跨页联动。
- 删除或移植代码时，保证没有残留未使用的代码、导入或文件。
