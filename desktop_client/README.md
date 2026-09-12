# 空间数据交叉验证工作台 · 桌面客户端框架

这是一个基于 Qt 的 Windows 桌面客户端框架，不依赖浏览器。当前版本完成了界面、页面导航、演示数据、参数面板、任务状态和多语言算法调用接口；真实算法和真实数据可以由小组后续替换。

## 技术结构

```text
desktop_client/
├─ main.py                         # 桌面程序入口
├─ app/
│  ├─ main_window.py               # 主窗口与页面导航
│  ├─ pages.py                     # 工作台、数据、预处理、结果页面
│  ├─ widgets.py                   # 地图画布、指标卡、流程控件
│  ├─ theme.py                     # Qt 样式
│  └─ qt_compat.py                 # PySide6 / PyQt6 兼容层
├─ core/
│  ├─ models.py                    # 数据模型与结果模型
│  ├─ project.py                   # 项目与数据目录
│  ├─ engine.py                    # 分析任务调度
│  ├─ io/
│  │  ├─ readers.py                # 数据读取器占位接口
│  │  ├─ data_registry.py          # CSV / GeoTIFF / GeoPackage 登记
│  │  └─ exporters.py              # 报告和清单导出
│  └─ algorithms/
│     ├─ base.py                   # 算法统一接口
│     ├─ python_runner.py          # Python 子进程适配器
│     ├─ r_runner.py               # Rscript 子进程适配器
│     └─ stubs/                    # 可替换的演示算法
└─ config/
   └─ default_config.json
```

## 启动

在 `desktop_client` 目录执行：

```powershell
python -m pip install -r requirements.txt
python main.py
```

也可以直接运行：

```powershell
.\run_client.ps1
```

## 接入真实算法

算法统一接收一个 JSON 配置文件，并输出一个 JSON 结果文件。界面不需要知道算法使用 Python 还是 R。

Python 算法入口：

```text
core/algorithms/stubs/gwr_placeholder.py
```

R 算法入口：

```text
core/algorithms/stubs/gwr_placeholder.R
```

将占位脚本替换为真实实现，保持输入输出字段结构即可。真实项目可以在 R 中使用 `sf`、`terra`、`GWmodel`、`jsonlite`，在 Python 中使用 `pandas`、`geopandas`、`rasterio`、`shapely`、`pyproj`。

## 打包

```powershell
python -m pip install pyinstaller
pyinstaller --noconsole --name SpatialValidationClient main.py
```

如果需要使用 R 算法，建议在“系统设置”中配置 `Rscript.exe` 路径，或者在部署包中附带经过验证的 R 运行环境。

## 代码接入位置

- 要接入 CSV、GeoTIFF、GeoPackage 的真实元数据读取，修改 `core/io/readers.py`。
- 要接入真实数据导入和质量检查，修改 `core/project.py` 和 `core/io/data_registry.py`。
- 要接入 Python 算法，替换 `core/algorithms/stubs/gwr_placeholder.py`。
- 要接入 R 算法，替换 `core/algorithms/stubs/gwr_placeholder.R`。
- 要串联多语言流程，在 `core/engine.py` 的混合调度分支中加入 Python 预处理、R 建模和结果汇总。
