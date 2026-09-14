"""分层设色：数值分级与色带生成（纯逻辑，无 Qt 依赖）。

供工作台地图渲染用：把某个数值字段分成若干等级，返回断点、每要素的级号，
以及对应的颜色列表。
"""
import bisect
import math

METHODS = ["自然间断点", "等间隔", "分位数", "手动"]

# ColorBrewer 风格色带锚点（浅→深 / 蓝→白→红）
_SEQUENTIAL = ["#ffffd9", "#c7e9b4", "#7fcdbb", "#41b6c4", "#1d91c0", "#225ea8", "#0c2c84"]
_DIVERGING = ["#2166ac", "#67a9cf", "#d1e5f0", "#f7f7f7", "#fddbc7", "#ef8a62", "#b2182b"]


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


def _jenks_breaks(values, n_classes):
    """Jenks 自然间断点：动态规划最小化类内平方和。"""
    values = sorted(values)
    m = len(values)
    if n_classes >= m:
        return [values[0]] + values + [values[-1]]

    prefix = [0.0] * (m + 1)
    prefix_sq = [0.0] * (m + 1)
    for i, v in enumerate(values):
        prefix[i + 1] = prefix[i] + v
        prefix_sq[i + 1] = prefix_sq[i] + v * v

    def ssd(i, j):  # values[i:j] 的离差平方和
        if j <= i:
            return 0.0
        s = prefix[j] - prefix[i]
        sq = prefix_sq[j] - prefix_sq[i]
        c = j - i
        return sq - s * s / c

    inf = float("inf")
    dp = [[inf] * (m + 1) for _ in range(n_classes + 1)]
    split = [[0] * (m + 1) for _ in range(n_classes + 1)]
    dp[0][0] = 0.0
    for k in range(1, n_classes + 1):
        for i in range(1, m + 1):
            best = inf
            best_j = 0
            for j in range(k - 1, i):
                cost = dp[k - 1][j] + ssd(j, i)
                if cost < best:
                    best = cost
                    best_j = j
            dp[k][i] = best
            split[k][i] = best_j

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
