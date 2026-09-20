# 几何数据算法

桌面客户端当前接入“外接矩形法几何交叉验证”。算法实现位于：

```text
desktop_client/core/algorithms/scripts/geometry/geometry_validation.py
```

用户在工作台选择两个 SHP、A/B 类别字段和类别映射后运行。默认输出到本目录的 `results/run_年月日_时分秒/`：

- `tables/`：总体汇总、分类汇总、匹配明细、GW 指标和运行元数据；
- `figures/`：面 IoU、质心距离、面积误差和周长误差4张3×3综合图；
- `report/`：几何交叉验证综合报告。

`results/` 是运行产物，已加入 `.gitignore`，不会作为源代码提交。

对于百万级数据，建议先仅勾选一个类别完成快速试算，再执行全部类别。全类运行可能持续数分钟，并需要约 2 GB 可用内存。
