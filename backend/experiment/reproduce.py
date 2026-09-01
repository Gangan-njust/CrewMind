"""实验结果可复现：生成一键复现包（配置快照 + 环境 + 脚本）"""
from __future__ import annotations

import io
import json
import platform
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config import PROJECT_ROOT, settings
from backend.storage.experiment_store import experiment_store

REPRODUCE_DIR_NAME = "reproduce"
DEFAULT_REQUIREMENTS = [
  "numpy>=1.24",
  "pandas>=2.0",
  "scikit-learn>=1.3",
  "scipy>=1.10",
  "matplotlib>=3.7",
]

_TRAIN_HINT = (
  "# 在这里填入实际训练/评估入口。\n"
  "# 示例：\n"
  "#   python train.py --config config.yaml\n"
  "#   python evaluate.py --checkpoint model.pt\n"
)


def _safe_title(title: str) -> str:
  return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", title).strip("_")[:40] or "experiment"


def _reproduce_dir(experiment_id: str) -> Path:
  return PROJECT_ROOT / settings.experiment_dir / experiment_id / REPRODUCE_DIR_NAME


def _render_requirements(config: dict) -> str:
  lines = []
  env = config.get("environment", {}) or {}
  extra = env.get("python_packages")
  if isinstance(extra, list):
    lines.extend(str(p) for p in extra if str(p).strip())
  lines.extend(DEFAULT_REQUIREMENTS)
  seen: set[str] = set()
  result = []
  for line in lines:
    base = re.split(r"[=<>~!]", line, maxsplit=1)[0].strip().lower()
    if base and base in seen:
      continue
    if base:
      seen.add(base)
    result.append(line)
  return "\n".join(result) + "\n"


def _render_reproduce_sh(experiment_id: str, title: str, entrypoint: str) -> str:
  venv = ".venv"
  return f"""#!/usr/bin/env bash
# 一键复现脚本 - {title}
# 用法: bash reproduce.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "==> 创建虚拟环境: {venv}"
python3 -m venv {venv}
source {venv}/bin/activate

echo "==> 安装依赖"
pip install -r requirements.txt

echo "==> 复现配置"
python -c "import json; json.dump(json.load(open('reproduce.json')), open('reproduce.json', 'w'), ensure_ascii=False, indent=2)"

echo "==> 运行训练/评估入口"
{entrypoint or "# TODO: 填入复现入口命令，例如 python train.py --config config.yaml"}

echo "==> 复现完成"
"""
def _render_readme(title: str, config: dict) -> str:
  code_version = (config.get("code_version") or {}).get("git_commit") or config.get("code_version")
  env = config.get("environment", {}) or {}
  return f"""# {title} - 复现说明

本目录为实验的完整复现包，包含实验配置快照、运行环境与一键复现脚本。

## 快速复现
1. 确保已安装 Python 3.10+
2. 执行 `bash reproduce.sh`（Windows 可参考下面手动步骤）

### 手动步骤（Windows）
```
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
{_TRAIN_HINT}
```

## 配置摘要
- 实验 ID：见 reproduce.json
- 代码版本：{code_version or "未记录"}
- Python：{env.get("python_version") or platform.python_version()}
- 操作系统：{env.get("os") or platform.platform()}
- 依赖：见 requirements.txt

## 文件清单
- `reproduce.json` — 实验元数据与配置快照（超参数、环境、代码版本、数据/文件清单）
- `config.yaml` — 超参数配置
- `requirements.txt` — Python 依赖
- `reproduce.sh` — 一键复现脚本
"""


def _render_config_yaml(config: dict) -> str:
  hyperparams = config.get("hyperparameters", {}) or {}
  lines = ["# 实验超参数配置", "hyperparameters:"]
  if not hyperparams:
    lines.append("  # (未记录)")
  for key, value in hyperparams.items():
    if isinstance(value, (dict, list)):
      lines.append(f"  {key}: {json.dumps(value, ensure_ascii=False)}")
    else:
      lines.append(f"  {key}: {value}")
  env = config.get("environment", {}) or {}
  lines.append("")
  lines.append("environment:")
  for key, value in env.items():
    if isinstance(value, (dict, list)):
      lines.append(f"  {key}: {json.dumps(value, ensure_ascii=False)}")
    else:
      lines.append(f"  {key}: {value}")
  return "\n".join(lines) + "\n"


def _metrics_summary(metrics: list[dict]) -> dict[str, dict]:
  by_name: dict[str, dict] = {}
  for m in metrics:
    name = m["metric_name"]
    summary = by_name.setdefault(name, {"count": 0, "last_value": None, "last_step": None})
    summary["count"] += 1
    if m.get("step") is not None:
      summary["last_step"] = m["step"]
    if m.get("value") is not None:
      summary["last_value"] = m["value"]
  return by_name


def build_reproduce_manifest(experiment_id: str, user_id: str, *, entrypoint: str = "") -> dict[str, Any]:
  """在实验目录下生成复现包文件，返回文件清单。"""
  exp = experiment_store.get_experiment(experiment_id, user_id)
  config = exp.get("config", {}) or {}
  title = exp.get("title", "实验")
  now = datetime.now().isoformat(timespec="seconds")

  manifest = {
    "schema_version": "1.0",
    "experiment_id": experiment_id,
    "experiment_title": title,
    "generated_at": now,
    "status": exp.get("status", ""),
    "progress": exp.get("progress", 0),
    "config": config,
    "expected_metrics": exp.get("expected_metrics", []),
    "datasets": [
      {"filename": d["filename"], "file_type": d["file_type"], "row_count": d["row_count"]}
      for d in exp.get("datasets", [])
    ],
    "files": [
      {"filename": f["filename"], "file_type": f["file_type"], "version": f["version"]}
      for f in exp.get("files", [])
    ],
    "metrics_summary": _metrics_summary(exp.get("metrics", [])),
  }

  dest_dir = _reproduce_dir(experiment_id)
  dest_dir.mkdir(parents=True, exist_ok=True)

  entrypoint = entrypoint or (config.get("entrypoint") or "")
  generated = []

  files = {
    "reproduce.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    "config.yaml": _render_config_yaml(config),
    "requirements.txt": _render_requirements(config),
    "reproduce.sh": _render_reproduce_sh(experiment_id, title, entrypoint),
    "README.md": _render_readme(title, config),
  }
  for name, content in files.items():
    path = dest_dir / name
    path.write_text(content, encoding="utf-8")
    generated.append({"filename": name, "size": path.stat().st_size})

  return {
    "experiment_id": experiment_id,
    "generated_at": now,
    "manifest": manifest,
    "files": generated,
    "entrypoint": entrypoint,
    "download_url": f"/api/experiment/experiments/{experiment_id}/reproduce/download",
  }


def build_reproduce_zip(experiment_id: str, user_id: str, *, entrypoint: str = "") -> tuple[bytes, str]:
  """将复现包打成 zip，返回 (bytes, zip文件名)。"""
  build_reproduce_manifest(experiment_id, user_id, entrypoint=entrypoint)
  exp = experiment_store.get_experiment(experiment_id, user_id)
  zip_name = f"{_safe_title(exp.get('title', 'experiment'))}_reproduce.zip"
  dest_dir = _reproduce_dir(experiment_id)

  buf = io.BytesIO()
  with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(dest_dir.iterdir()):
      if path.is_file():
        zf.write(path, arcname=f"reproduce/{path.name}")
  return buf.getvalue(), zip_name

