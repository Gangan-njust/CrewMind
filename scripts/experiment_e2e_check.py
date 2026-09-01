"""端到端验证：配置保存 / 指标记录 / 文件版本控制 / 复现包生成"""
import tempfile
from pathlib import Path

from backend.config import settings
from backend.storage.database import setup_database, get_session
from backend.storage.experiment_store import experiment_store
from backend.storage.models import User
from backend.experiment.reproduce import build_reproduce_manifest
from backend.experiment.compare_multi import compare_experiments

tmp = Path(tempfile.mkdtemp())
settings.data_dir = tmp
settings.experiment_dir = tmp / "experiments"
setup_database()

with get_session() as session:
  from datetime import datetime
  if not session.get(User, "user-1"):
    session.add(User(id="user-1", username="tester", password_hash="x", created_at=datetime.now()))
    session.commit()

# 1. 创建实验
exp = experiment_store.create_experiment(
  "user-1", title="端到端测试实验", description="验证实验模块",
  config={"hyperparameters": {"lr": 0.01, "batch_size": 32}},
  steps=[{"id": "s1", "name": "数据准备", "status": "done"}, {"id": "s2", "name": "训练", "status": "todo"}],
)
exp_id = exp["id"]
print("[1] create OK, config=", exp["config"], "steps=", exp["steps"], "progress=", exp["progress"])

# 2. 保存配置（合并）
exp = experiment_store.save_config(exp_id, "user-1", {"environment": {"python_version": "3.12"}, "code_version": {"git_commit": "abc123"}})
assert exp["config"]["hyperparameters"]["lr"] == 0.01
assert exp["config"]["environment"]["python_version"] == "3.12"
print("[2] save_config merge OK")

# 3. 更新进度
exp = experiment_store.update_experiment(exp_id, "user-1", progress=50, current_step="s2", steps=exp["steps"])
assert exp["progress"] == 50
print("[3] update progress OK")

# 4. 记录指标
saved = experiment_store.record_metrics(exp_id, "user-1", [
  {"metric_name": "loss", "step": 1, "value": 0.5},
  {"metric_name": "loss", "step": 2, "value": 0.3},
  {"metric_name": "accuracy", "step": 1, "value": 0.85, "unit": "%"},
])
assert len(saved) == 3
names = experiment_store.list_metric_names(exp_id, "user-1")
assert names == ["accuracy", "loss"], names
points = experiment_store.list_metrics(exp_id, "user-1", "loss")
assert [p["value"] for p in points] == [0.5, 0.3]
print("[4] record_metrics OK, names=", names)

# 5. 文件版本控制：同名上传两次
f1 = experiment_store.save_file(exp_id, "user-1", filename="model.pt", content=b"model-v1", file_type="model")
f2 = experiment_store.save_file(exp_id, "user-1", filename="model.pt", content=b"model-v2", file_type="model")
assert f1["version"] == 1 and f2["version"] == 2
files = experiment_store.list_files(exp_id, "user-1")
assert len(files) == 2
got, path = experiment_store.get_file(f2["id"], "user-1")
assert path.read_bytes() == b"model-v2"
print("[5] file versioning OK: v1 + v2")

# 6. 详情包含新字段
detail = experiment_store.get_experiment(exp_id, "user-1")
assert detail["metric_count"] == 3 and detail["file_count"] == 2
print("[6] get_experiment detail OK")

# 7. 复现包
rep = build_reproduce_manifest(exp_id, "user-1", entrypoint="python train.py")
names = {f["filename"] for f in rep["files"]}
assert "reproduce.sh" in names
print("[7] reproduce manifest OK:", sorted(names))

# 8. 多实验对比（mock 第二个实验）
import backend.experiment.compare_multi as cm
orig = cm.experiment_store.get_experiment
cm.experiment_store.get_experiment = lambda eid, uid: {
  "id": eid, "title": f"实验-{eid}", "status": "active", "progress": 40,
  "entry_count": 0, "dataset_count": 0, "metric_count": 1, "file_count": 0,
  "config": {}, "metrics": [{"metric_name": "accuracy", "step": 1, "value": 0.9, "unit": "%"}],
}
result = compare_experiments([exp_id, "exp2"], "user-1", metric_names=["accuracy"])
cm.experiment_store.get_experiment = orig
assert len(result["experiments"]) == 2
print("[8] compare_multi OK, charts=", len(result["charts"]))

# 9. 级联删除
experiment_store.delete_experiment(exp_id, "user-1")
assert len(experiment_store.list_experiments("user-1")) == 0
print("[9] delete cascade OK")

print("ALL END-TO-END CHECKS PASSED")
