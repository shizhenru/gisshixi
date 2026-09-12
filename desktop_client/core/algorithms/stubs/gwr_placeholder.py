import json
import sys
from pathlib import Path


def main():
    config_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    config = json.loads(config_path.read_text(encoding="utf-8"))
    bandwidth = float(config.get("bandwidth", 0.62))
    local_values = [round(max(0.45, min(0.95, 0.56 + ((i * 13) % 37) / 100 + bandwidth / 10)), 3) for i in range(18)]
    result = {
        "status": "success",
        "engine": "Python 占位算法",
        "metrics": {
            "mae": "8.42",
            "rmse": "13.67",
            "correlation": "0.82",
            "local_r2": f"{sum(local_values) / len(local_values):.2f}",
            "difference_area": "18.6%",
            "duration": "00:03",
        },
        "message": "Python 算法适配器已执行。请将本脚本替换为真实预处理或 GWR 实现。",
        "local_values": local_values,
        "config": config,
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
