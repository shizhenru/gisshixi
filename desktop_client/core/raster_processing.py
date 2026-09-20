from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np


RASTER_SUFFIXES = {".tif", ".tiff", ".img", ".asc"}

# 对齐后的栅格统一使用同一种数据类型与 nodata，保证拉帘对比等显示效果一致。
UNIFIED_DTYPE = "float32"
UNIFIED_NODATA = -9999.0

# 重投影并行线程数（须为整数；"all_cpus" 字符串会在 GDAL 内部与 1 做比较时报错）。
WARP_NUM_THREADS = min(8, max(2, os.cpu_count() or 4))


@dataclass
class RasterPreprocessResult:
    status: str
    message: str
    output_dir: str
    reference: str = ""
    selected_sources: list[str] | None = None
    processed: list[dict[str, Any]] | None = None
    checks: list[str] | None = None
    warnings: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["processed"] = payload["processed"] or []
        payload["selected_sources"] = payload["selected_sources"] or []
        payload["checks"] = payload["checks"] or []
        payload["warnings"] = payload["warnings"] or []
        return payload


def is_raster_source(source) -> bool:
    return Path(source.path).suffix.lower() in RASTER_SUFFIXES or "栅格" in source.data_type


def is_aligned_output(path) -> bool:
    """判断路径是否为栅格对齐的输出产物（对齐结果统一以 aligned_ 前缀命名）。"""
    return Path(path).name.startswith("aligned_")


def collect_raster_sources(sources) -> list:
    return [source for source in sources if is_raster_source(source)]


class RasterPreprocessor:
    """Align imported rasters to one grid before heterogeneous validation."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.output_dir = project_dir / ".runtime" / "raster_preprocess"
        self.manifest_path = self.output_dir / "manifest.json"

    def preprocess(self, sources, reference_path: str = "", selected_paths=None, progress_callback=None) -> RasterPreprocessResult:
        rasters = collect_raster_sources(sources)
        if selected_paths is not None:
            selected_set = {str(path) for path in selected_paths}
            rasters = [source for source in rasters if source.path in selected_set]
        selected_sources = [source.path for source in rasters]
        if len(rasters) < 2:
            return RasterPreprocessResult(
                status="error",
                message="请至少选择两个栅格数据集后再执行预处理。",
                output_dir=str(self.output_dir),
                selected_sources=selected_sources,
            )

        try:
            import rasterio
            from rasterio.enums import Resampling
            from rasterio.warp import reproject
        except ImportError:
            return RasterPreprocessResult(
                status="error",
                message="缺少 rasterio，无法执行栅格坐标系、分辨率和范围统一。请安装 rasterio 后重试。",
                output_dir=str(self.output_dir),
                selected_sources=selected_sources,
                warnings=["pip install rasterio"],
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        reference = self._pick_reference(rasters, reference_path)
        processed = []
        checks = []
        warnings = []

        with rasterio.open(reference.path) as ref:
            if ref.count < 1:
                raise ValueError(f"参考栅格没有可读取波段：{reference.name}")
            target_profile = ref.profile.copy()
            target_profile.update(
                driver="GTiff",
                count=1,
                compress="lzw",
            )
            target_crs = ref.crs
            if target_crs is None:
                raise ValueError(f"参考栅格缺少坐标系定义：{reference.name}")
            target_transform = ref.transform
            target_width = ref.width
            target_height = ref.height
            target_bounds = ref.bounds
            target_res = ref.res

        for i, source in enumerate(rasters):
            if progress_callback:
                progress_callback(f"正在对齐 {source.name}（{i + 1}/{len(rasters)}）…")
            in_path = Path(source.path)
            out_path = self.output_dir / f"aligned_{in_path.stem}.tif"
            # 防御：对齐结果只写到输出目录，绝不覆盖/改写原始数据文件。
            if out_path.resolve() == in_path.resolve():
                raise ValueError(f"对齐输出路径与源文件冲突，已拒绝覆盖：{in_path.name}")
            with rasterio.open(in_path) as src:
                if src.count != 1:
                    raise ValueError(f"栅格必须是单波段：{source.name} 当前为 {src.count} 个波段")
                if src.crs is None:
                    raise ValueError(f"栅格缺少坐标系定义：{source.name}")
                src_crs = src.crs
                src_res = src.res
                src_bounds = src.bounds
                src_nodata = src.nodata
                # 统一识别无效像元：源声明了 nodata 时由 reproject 按值掩膜；
                # 未声明 nodata 且为浮点型时，把 NaN 也当无效像元屏蔽（传 NaN 作为源
                # nodata，reproject 会分块流式处理，避免整幅读入内存导致大栅格溢出）。
                if src_nodata is None and np.issubdtype(src.dtypes[0], np.floating):
                    src_nodata = float("nan")
                # 统一输出 dtype 与 nodata：源 nodata 仅用于读取时识别无效像元，
                # 输出统一为 UNIFIED_DTYPE / UNIFIED_NODATA，保证显示效果一致。
                profile = target_profile.copy()
                profile.update(
                    dtype=UNIFIED_DTYPE,
                    nodata=UNIFIED_NODATA,
                )
                with rasterio.open(out_path, "w", **profile) as dst:
                    reproject(
                        source=rasterio.band(src, 1),
                        destination=rasterio.band(dst, 1),
                        src_transform=src.transform,
                        src_crs=src_crs,
                        src_nodata=src_nodata,
                        dst_transform=target_transform,
                        dst_crs=target_crs,
                        dst_nodata=UNIFIED_NODATA,
                        resampling=Resampling.bilinear,
                        num_threads=WARP_NUM_THREADS,
                    )
                with rasterio.open(out_path, "r+") as dst:
                    dst.build_overviews([2, 4, 8, 16, 32, 64], Resampling.average)

            if source.path == reference.path:
                checks.append(f"{source.name}: 作为参考网格")
            else:
                if src_crs != target_crs:
                    checks.append(f"{source.name}: CRS 已统一到参考栅格")
                if tuple(round(v, 12) for v in src_res) != tuple(round(v, 12) for v in target_res):
                    checks.append(f"{source.name}: 分辨率已统一到参考栅格")
                if src_bounds != target_bounds:
                    checks.append(f"{source.name}: 范围已裁剪/重采样到参考栅格")

            processed.append(
                {
                    "name": source.name,
                    "source_path": source.path,
                    "aligned_path": str(out_path),
                    "crs": str(target_crs) if target_crs else "",
                    "width": target_width,
                    "height": target_height,
                    "resolution": [target_res[0], target_res[1]],
                    "bounds": [target_bounds.left, target_bounds.bottom, target_bounds.right, target_bounds.top],
                    "dtype": UNIFIED_DTYPE,
                    "nodata": UNIFIED_NODATA,
                }
            )

        if not checks:
            checks.append("所有栅格已输出为统一网格。")

        result = RasterPreprocessResult(
            status="success",
            message=f"栅格预处理完成：已对齐 {len(processed)} 个数据集。",
            output_dir=str(self.output_dir),
            reference=reference.path,
            selected_sources=selected_sources,
            processed=processed,
            checks=checks,
            warnings=warnings,
        )
        self.manifest_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def latest_manifest(self) -> dict[str, Any] | None:
        if not self.manifest_path.exists():
            return None
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _pick_reference(self, rasters, reference_path: str):
        if reference_path:
            for source in rasters:
                if source.path == reference_path:
                    return source
        return rasters[0]

    def clear_outputs(self) -> None:
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
