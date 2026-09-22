"""分层设色：数值分级与色带生成（纯逻辑，无 Qt 依赖）。

供工作台地图渲染用：把某个数值字段分成若干等级，返回断点、每要素的级号，
以及对应的颜色列表。
"""
import bisect
import math

import numpy as _np

METHODS = ["自然间断点", "等间隔", "分位数", "唯一值", "手动"]

# ColorBrewer 风格色带锚点（浅→深 / 蓝→白→红）
_SEQUENTIAL = ["#ffffd9", "#c7e9b4", "#7fcdbb", "#41b6c4", "#1d91c0", "#225ea8", "#0c2c84"]
_DIVERGING = ["#2166ac", "#67a9cf", "#d1e5f0", "#f7f7f7", "#fddbc7", "#ef8a62", "#b2182b"]
# 类别色板（Tableau 风格）：唯一值设色用，相邻类别颜色区分明显
_CATEGORICAL = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948",
    "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac", "#86bcb6", "#d37295",
]

# 唯一值最多保留的类别数：超出则按出现次数保留高频类别，其余归入「其他」。
# 逐要素唯一的字段（如 OBJECTID）会有十几万类，不设限则图例与配色都不可读。
_UNIQUE_MAX_CATEGORIES = 64

# Jenks 断点计算的最大参与值数：超过则等间隔抽样后再做动态规划。
# 取 1024 时 10 级约 50ms；分级数通常只有 5~7 级，该抽样密度已足够刻画分布。
_JENKS_MAX_VALUES = 1024


def _is_missing(v):
    return v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))


def classify(values, method="自然间断点", n_classes=5, manual_breaks=None):
    """把数值列表分级。

    返回 (breaks, indices)：
      breaks  长度 = 级数 + 1 的递增断点（含最小/最大值）。
      indices 与 values 等长，每个元素是级号(0..级数-1)，缺失值为 None。
    """
    valid = [v for v in values if not _is_missing(v)]
    if not valid:
        return [], [None] * len(values)

    lo, hi = min(valid), max(valid)
    n = max(1, int(n_classes))

    if lo == hi:
        breaks = [lo, hi]
    elif method == "等间隔":
        breaks = [lo + (hi - lo) * i / n for i in range(n + 1)]
    elif method == "分位数":
        breaks = _quantile_breaks(valid, n)
    elif method == "手动":
        breaks = _manual_breaks(manual_breaks, lo, hi)
    else:  # 自然间断点
        breaks = _jenks_breaks(valid, n)

    breaks = _dedupe_breaks(breaks)
    indices = []
    for v in values:
        if _is_missing(v):
            indices.append(None)
        else:
            k = bisect.bisect_right(breaks, v) - 1
            indices.append(max(0, min(k, len(breaks) - 2)))
    return breaks, indices


def _unique_sort_key(v):
    """唯一值排序键：数值在前按大小排，其余在后按字符串排，避免混合类型无法比较。"""
    return (0, v) if isinstance(v, (int, float)) and not isinstance(v, bool) else (1, str(v))


def _unique_label(v):
    """唯一值的图例显示名：整数型浮点去掉小数点，其余直接转字符串。"""
    if isinstance(v, float) and abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return str(v)


def classify_unique(values, max_categories=_UNIQUE_MAX_CATEGORIES):
    """按字段的不同取值分级（唯一值 / 类别设色）。

    返回 (labels, indices)：
      labels  类别显示名，按取值升序排列；发生归并时末位追加「其他」
      indices 与 values 等长，给出每个值所属类别的下标，缺失值为 None

    类别数超过 max_categories 时，按出现次数保留前 max_categories-1 类，
    其余取值统一归入「其他」，避免逐要素唯一的高基数字段撑爆图例与配色。
    """
    counts: dict = {}
    for v in values:
        if not _is_missing(v):
            counts[v] = counts.get(v, 0) + 1
    if not counts:
        return [], [None] * len(values)

    uniques = sorted(counts, key=_unique_sort_key)
    merged = len(uniques) > max_categories
    if merged:
        kept = sorted(uniques, key=lambda v: (-counts[v], _unique_sort_key(v)))[: max_categories - 1]
        uniques = sorted(kept, key=_unique_sort_key)

    labels = [_unique_label(v) for v in uniques]
    if merged:
        labels.append("其他")
    index_of = {v: i for i, v in enumerate(uniques)}
    other = len(uniques)  # 归并类别的下标（未归并时不会用到）

    indices = []
    for v in values:
        if _is_missing(v):
            indices.append(None)
        else:
            indices.append(index_of.get(v, other))
    return labels, indices


def categorical_colors(n_colors):
    """唯一值设色用的类别色板：相邻类别颜色区分明显。

    类别多于预设色板长度时，按黄金角散布色相并轮换明度：等间隔取色相会让相邻类别
    只差几度、看起来几乎同色（64 类时相邻色差仅约 9），黄金角则把相邻类别推到色轮两端
    （同类数下相邻色差约 179）。
    """
    if n_colors <= 0:
        return []
    if n_colors <= len(_CATEGORICAL):
        return list(_CATEGORICAL[:n_colors])
    return [
        _hsl_to_hex((i * 0.6180339887) % 1.0, 0.60, 0.38 + 0.13 * (i % 3))
        for i in range(n_colors)
    ]


def _hsl_to_hex(h: float, s: float, lightness: float) -> str:
    """HSL（各分量 0~1）→ #rrggbb。"""
    def channel(offset: int) -> float:
        k = (offset + h * 12) % 12
        a = s * min(lightness, 1 - lightness)
        return lightness - a * max(-1, min(k - 3, 9 - k, 1))

    return "#{:02x}{:02x}{:02x}".format(
        round(255 * channel(0)), round(255 * channel(8)), round(255 * channel(4))
    )


def auto_colors(values, n_classes):
    """按数据特征自动选色带：含负值用发散色(蓝→白→红)，否则用单色渐变。"""
    valid = [v for v in values if not _is_missing(v)]
    if valid and min(valid) < 0:
        return diverging_colors(n_classes)
    return sequential_colors(n_classes)


def sequential_colors(n):
    return _ramp(_SEQUENTIAL, n)


def diverging_colors(n):
    return _ramp(_DIVERGING, n)


def _quantile_breaks(values, n):
    values = sorted(values)
    m = len(values)
    if n >= m:
        return [values[0]] + values + [values[-1]]

    def quantile(q):
        pos = q * (m - 1)
        lo = int(pos)
        hi = min(lo + 1, m - 1)
        frac = pos - lo
        return values[lo] * (1 - frac) + values[hi] * frac

    breaks = [values[0]]
    for i in range(1, n):
        breaks.append(quantile(i / n))
    breaks.append(values[-1])
    return breaks


def _jenks_sample(values, limit=_JENKS_MAX_VALUES):
    """把升序数值序列按等间隔抽样压缩到 limit 个以内（保留最小 / 最大值）。

    等间隔抽样在有序序列上等价于按数值分布均匀取点，能保持原始分布形态。
    """
    m = len(values)
    if m <= limit:
        return values
    step = (m - 1) / (limit - 1)
    return [values[min(m - 1, int(round(i * step)))] for i in range(limit)]


def _jenks_breaks(values, n_classes):
    """Jenks 自然间断点：动态规划最小化类内平方和。

    复杂度为 O(级数 × n²)，n 达万级时耗时以小时计（16 万个值约需数小时），
    会长时间阻塞界面。分级断点只需反映数值分布、无需逐值参与，故超过
    _JENKS_MAX_VALUES 时先按分布等间隔抽样，断点仍对全部数值生效。
    """
    values = _jenks_sample(sorted(values))
    m = len(values)
    if n_classes >= m:
        return [values[0]] + values + [values[-1]]

    # 前缀和用顺序累加（与逐值循环一致），保证与朴素实现逐位相同的断点。
    prefix = [0.0] * (m + 1)
    prefix_sq = [0.0] * (m + 1)
    for i, v in enumerate(values):
        prefix[i + 1] = prefix[i] + v
        prefix_sq[i + 1] = prefix_sq[i] + v * v
    prefix_arr = _np.asarray(prefix, dtype="float64")
    prefix_sq_arr = _np.asarray(prefix_sq, dtype="float64")

    # 状态转移把内层 j 循环整体矩阵化：ssd(i, j) = Σv² - (Σv)²/cnt，
    # 对排序后的样本一次性算全表（m 已抽样到 1024 以内，矩阵开销可控）。
    # 每行取 argmin 得首个最小值，与朴素实现「严格小于」的升序扫描一致。
    inf = float("inf")
    idx = _np.arange(m + 1)
    rows, cols = idx[:, None], idx[None, :]
    with _np.errstate(divide="ignore", invalid="ignore"):
        # 写成 x * x 而非 x ** 2：numpy 的幂运算末位可能不同，会破坏与朴素实现的逐位一致。
        delta = prefix_arr[rows] - prefix_arr[cols]
        # i == j 处 cnt 为 0 会除零，先算出再统一置为 inf
        ssd = prefix_sq_arr[rows] - prefix_sq_arr[cols] - delta * delta / (rows - cols)
    ssd = _np.where(cols < rows, ssd, inf)

    dp = [[inf] * (m + 1) for _ in range(n_classes + 1)]
    split = [[0] * (m + 1) for _ in range(n_classes + 1)]
    dp[0][0] = 0.0
    for k in range(1, n_classes + 1):
        # cost[i, j] = dp[k-1][j] + ssd(i, j)
        cost = _np.asarray(dp[k - 1], dtype="float64")[cols] + ssd
        best = _np.argmin(cost, axis=1)
        best_cost = cost[idx, best]
        for i in range(k, m + 1):
            dp[k][i] = float(best_cost[i])
            split[k][i] = int(best[i])

    starts = [0] * (n_classes + 1)
    starts[n_classes] = m
    i = m
    for k in range(n_classes, 0, -1):
        j = split[k][i]
        starts[k - 1] = j
        i = j

    breaks = [values[0]]
    for k in range(1, n_classes):
        breaks.append(values[starts[k] - 1])
    breaks.append(values[-1])
    return breaks


def _manual_breaks(manual, lo, hi):
    if not manual:
        return [lo, hi]
    cleaned = []
    for x in manual:
        try:
            cleaned.append(float(x))
        except (TypeError, ValueError):
            continue
    cleaned = sorted(c for c in cleaned if lo <= c <= hi)
    return [lo] + cleaned + [hi]


def _dedupe_breaks(breaks):
    out = []
    for b in breaks:
        if not out or b != out[-1]:
            out.append(b)
    if len(out) == 1:
        out.append(out[0])
    return out


def _ramp(anchor_hexes, n):
    anchors = [_hex_to_rgb(h) for h in anchor_hexes]
    if n <= 0:
        return []
    if n == 1:
        return [anchor_hexes[0]]
    out = []
    for i in range(n):
        t = i / (n - 1) * (len(anchors) - 1)
        j = int(t)
        frac = t - j
        if j >= len(anchors) - 1:
            out.append(anchor_hexes[-1])
        else:
            out.append(_rgb_to_hex(_interp(anchors[j], anchors[j + 1], frac)))
    return out


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _interp(c1, c2, t):
    return tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))


# 字段含义与分级解读提示（用于设色字段的悬停 tip）
FIELD_INFO = {
    "Local_R2": ("局部 R²（拟合优度）", "越接近 1 表示局部拟合越好（深色=好，浅色=差）"),
    "Coeff": ("GWR 斜率系数", "X 每变 1 单位、Y 变化多少；约等于 1 表示两数据一致"),
    "Corr": ("局部相关系数", "越接近 1 表示 X/Y 局部相关性越强"),
    "LME": ("局部平均误差（Y - X）", "正值（红）=Y 高于 X；负值（蓝）=Y 低于 X"),
    "LMAE": ("局部平均绝对误差", "值越大表示两数据差异越大"),
    "LMRE": ("局部平均相对误差", "相对 X 的误差比例，值越大差异越大"),
    "LRMSE": ("局部均方根误差", "对大误差更敏感，值越大差异越大"),
    "X2024_pop": ("2024 年人口", "单位为 ×10⁴"),
    "2024_pop": ("2024 年人口", "单位为 ×10⁴"),
    "worldpop": ("WorldPop 人口", "单位为 ×10⁴"),
    "ORNL_pop": ("ORNL 人口", "单位为 ×10⁴"),
    "name": ("市/地区名称", "文本字段，仅作标注"),
    "gb": ("行政区划代码", "文本字段"),
    "Province_n": ("所属省份", "文本字段"),
}
