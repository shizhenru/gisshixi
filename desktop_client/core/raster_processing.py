from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


RASTER_SUFFIXES = {".tif", ".tiff", ".img", ".asc"}


@dataclass
class RasterPreprocessResult:
    status: str
    message: str
    output_dir: str
    reference: str = ""
    processed: list[dict[str, Any]] | None = None
    checks: list[str] | None = None
    warnings: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["processed"] = payload["processed"] or []
        payload["checks"] = payload["checks"] or []
        payload["warnings"] = payload["warnings"] or []
        return payload


def is_raster_source(source) -> bool:
    return Path(source.path).suffix.lower() in RASTER_SUFFIXES or "栅格" in source.data_type


def collect_raster_sources(sources) -> list:
    return [source for source in sources if is_raster_source(source)]


class RasterPreprocessor:
    """Align imported rasters to one grid before heterogeneous validation."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.output_dir = project_dir / ".runtime" / "raster_preprocess"
        self.manifest_path = self.output_dir / "manifest.json"

    def preprocess(self, sources, reference_path: str = "") -> RasterPreprocessResult:
        rasters = collect_raster_sources(sources)
        if len(rasters) < 2:
            return RasterPreprocessResult(
                status="error",
                message="请至少导入两个栅格数据集后再执行预处理。",
                output_dir=str(self.output_dir),
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

        for source in rasters:
            in_path = Path(source.path)
            out_path = self.output_dir / f"aligned_{in_path.stem}.tif"
            with rasterio.open(in_path) as src:
                if src.count != 1:
                    raise ValueError(f"栅格必须是单波段：{source.name} 当前为 {src.count} 个波段")
                if src.crs is None:
                    raise ValueError(f"栅格缺少坐标系定义：{source.name}")
                src_crs = src.crs
                src_res = src.res
                src_bounds = src.bounds
                src_profile = src.profile
                nodata = src.nodata
                profile = target_profile.copy()
                profile.update(
                    dtype=src_profile.get("dtype", target_profile.get("dtype", "float32")),
                    nodata=nodata,
                )
                with rasterio.open(out_path, "w", **profile) as dst:
                    reproject(
                        source=rasterio.band(src, 1),
                        destination=rasterio.band(dst, 1),
                        src_transform=src.transform,
                        src_crs=src_crs,
                        src_nodata=nodata,
                        dst_transform=target_transform,
                        dst_crs=target_crs,
                        dst_nodata=nodata,
                        resampling=Resampling.bilinear,
                    )

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
                }
            )

        if not checks:
            checks.append("所有栅格已输出为统一网格。")

        result = RasterPreprocessResult(
            status="success",
            message=f"栅格预处理完成：已对齐 {len(processed)} 个数据集。",
            output_dir=str(self.output_dir),
            reference=reference.path,
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
