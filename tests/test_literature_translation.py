"""文献全文英译中测试（Mock LLM）"""
import asyncio
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.storage.database import get_session, setup_database
from backend.storage.literature_store import literature_store
from backend.storage.models import LiteratureRecord, User, WorkspaceRecord

ENGLISH_TEXT = (
  "Introduction\n\n"
  "Deep learning has achieved remarkable success in medical image analysis.\n\n"
  "Methods\n\n"
  "We trained a convolutional neural network on 10,000 labeled images.\n\n"
  "Results\n\n"
  "The model reached an accuracy of 92.3% [12], outperforming the baseline.\n"
)


@pytest.fixture(scope="module", autouse=True)
def _setup_db():
  setup_database()


def _make_literature(*, user_id: str | None = None, full_text: str = ENGLISH_TEXT) -> dict:
  owner = user_id or str(uuid.uuid4())
  ws_id = str(uuid.uuid4())
  lit_id = str(uuid.uuid4())
  now = datetime.now()
  with get_session() as session:
    if not user_id:
      session.add(User(
        id=owner,
        username=f"trans_{uuid.uuid4().hex[:8]}",
        password_hash="hash",
        created_at=now,
      ))
    session.add(WorkspaceRecord(
      id=ws_id, name="翻译测试库", description="", user_id=owner,
      current_selected_ids_json="[]", created_at=now, updated_at=now,
    ))
    session.add(LiteratureRecord(
      id=lit_id, workspace_id=ws_id, title="Deep Learning for Medical Imaging",
      authors_json='["Alice"]', journal="Nature", year=2024, doi="10.1/x",
      abstract="A study on CNN for diagnosis.", pdf_path="", full_text=full_text,
      uploaded_at=now, status="done",
    ))
    session.commit()
  return {"user_id": owner, "workspace_id": ws_id, "literature_id": lit_id}


def _fake_chat(counter: dict, prompts: list[str]):
  """模拟大模型流式返回中文译文"""
  async def fake_chat(messages, **kwargs):
    counter["calls"] = counter.get("calls", 0) + 1
    prompts.append(messages[0]["content"])
    text = f"【第{counter['calls']}段译文】深度学习在医学图像分析中取得了显著成功。"

    async def stream():
      for i in range(0, len(text), 6):
        yield text[i:i + 6]

    return stream()

  return fake_chat


def test_split_for_translation_keeps_paragraphs_whole():
  from backend.literature.translator import split_for_translation

  paragraphs = [f"Paragraph {i} " + "x" * 40 for i in range(6)]
  text = "\n\n".join(paragraphs)
  segments = split_for_translation(text, max_chars=120)
  assert len(segments) > 1
  assert all(len(segment) <= 120 for segment in segments)
  for paragraph in paragraphs:
    assert any(paragraph in segment for segment in segments)


def test_split_for_translation_hard_splits_long_paragraph():
  from backend.literature.translator import split_for_translation

  segments = split_for_translation("a" * 250, max_chars=100)
  assert len(segments) == 3
  assert all(len(segment) <= 100 for segment in segments)
  assert "".join(segments) == "a" * 250


def test_split_for_translation_empty_text():
  from backend.literature.translator import split_for_translation

  assert split_for_translation("   \n\n ") == []


@pytest.mark.asyncio
async def test_translate_literature_persists_and_resumes():
  from backend.literature.translator import (
    get_translation_payload,
    split_for_translation,
    translate_literature,
  )

  lit = _make_literature()
  counter: dict = {}
  prompts: list[str] = []
  glossary = "convolutional neural network=卷积神经网络"

  with patch(
    "backend.literature.translator.llm_client.chat",
    new=AsyncMock(side_effect=_fake_chat(counter, prompts)),
  ):
    result = await translate_literature(lit["literature_id"], glossary=glossary, max_chars=120)
    expected_segments = len(split_for_translation(ENGLISH_TEXT, 120))
    assert counter["calls"] == expected_segments
    assert expected_segments > 1

    # 已完成整篇：再次调用（force=False）不再请求大模型
    again = await translate_literature(lit["literature_id"], max_chars=120)

  assert result["status"] == "done"
  assert result["target_language"] == "zh"
  assert result["segment_done"] == expected_segments
  assert result["markdown"].count("段译文") == expected_segments
  assert result["translation_chars"] == len(result["markdown"])
  assert glossary in prompts[0]
  assert "学术翻译规范" in prompts[0]

  assert again["status"] == "done"
  assert again["markdown"] == result["markdown"]
  assert counter["calls"] == expected_segments

  stored = get_translation_payload(lit["literature_id"])
  assert stored["markdown"] == result["markdown"]
  # 分段译文与 markdown 互为投影
  assert stored["segments"][0]["translation"].strip()
  assert stored["segments"][0]["char_end"] > stored["segments"][0]["char_start"]

  detail = literature_store.get_literature(
    lit["workspace_id"], lit["literature_id"], lit["user_id"]
  )
  assert detail["translation"]["status"] == "done"
  assert detail["translation"]["segment_done"] == detail["translation"]["segment_total"]
  # 列表接口不返回全文，避免响应过大
  assert "markdown" not in detail["translation"]
  assert "segments" not in detail["translation"]


@pytest.mark.asyncio
async def test_translate_resumes_after_failure():
  from backend.literature.translator import get_translation_payload, translate_literature

  lit = _make_literature()
  counter: dict = {}
  prompts: list[str] = []
  happy = _fake_chat(counter, prompts)

  async def failing_chat(messages, **kwargs):
    counter["calls"] = counter.get("calls", 0) + 1
    if counter["calls"] == 2:
      raise RuntimeError("服务限流")
    text = "【第1段译文】首段译文。"

    async def stream():
      yield text

    return stream()

  with patch(
    "backend.literature.translator.llm_client.chat",
    new=AsyncMock(side_effect=failing_chat),
  ):
    with pytest.raises(ValueError):
      await translate_literature(lit["literature_id"], max_chars=120)

  partial = get_translation_payload(lit["literature_id"])
  assert partial["status"] == "failed"
  assert partial["segment_done"] == 1
  assert "服务限流" in partial["error"]

  counter["calls"] = 0
  with patch(
    "backend.literature.translator.llm_client.chat",
    new=AsyncMock(side_effect=happy),
  ):
    result = await translate_literature(lit["literature_id"], max_chars=120)

  assert result["status"] == "done"
  assert result["segment_done"] == result["segment_total"]
  # 已完成的第 1 段不再重复翻译
  assert counter["calls"] == result["segment_total"] - 1
  assert result["segments"][0]["translation"] == "【第1段译文】首段译文。"


@pytest.mark.asyncio
async def test_translate_empty_content_raises():
  from backend.literature.translator import translate_literature

  lit = _make_literature(full_text="")
  with pytest.raises(ValueError) as exc:
    await translate_literature(lit["literature_id"])
  assert "文献内容为空" in str(exc.value)


def test_translate_api_stream_and_translation_endpoint():
  suffix = uuid.uuid4().hex[:8]
  with TestClient(app) as client:
    registered = client.post(
      "/api/auth/register",
      json={"username": f"transapi_{suffix}", "password": "test123456"},
    )
    assert registered.status_code in (200, 201), registered.text
    headers = {"Authorization": f"Bearer {registered.json()['token']}"}
    user_id = client.get("/api/auth/me", headers=headers).json()["id"]

    lit = _make_literature(user_id=user_id)
    ws_id, lit_id = lit["workspace_id"], lit["literature_id"]
    counter: dict = {}
    prompts: list[str] = []

    with patch(
      "backend.literature.translator.llm_client.chat",
      new=AsyncMock(side_effect=_fake_chat(counter, prompts)),
    ):
      res = client.post(
        f"/api/workspaces/{ws_id}/literatures/{lit_id}/translate",
        headers=headers,
        json={"stream": True, "glossary": "deep learning=深度学习"},
      )
      assert res.status_code == 200, res.text
      assert "event: start" in res.text
      assert "event: token" in res.text
      assert "event: done" in res.text
      assert "deep learning=深度学习" in prompts[0]

      # 全文译文可单独读取（列表接口只返回元信息）
      got = client.get(
        f"/api/workspaces/{ws_id}/literatures/{lit_id}/translation", headers=headers
      )
      assert got.status_code == 200, got.text
      body = got.json()
      assert body["status"] == "done"
      assert body["markdown"].count("段译文") == body["segment_total"]
      assert len(body["segments"]) == body["segment_total"]

      items = client.get(f"/api/workspaces/{ws_id}/literatures", headers=headers).json()
      item = next(one for one in items if one["id"] == lit_id)
      assert item["translation"]["status"] == "done"
      assert item["translation"]["segment_done"] == item["translation"]["segment_total"]
      assert "markdown" not in item["translation"]

    # 非流式接口
    with patch(
      "backend.literature.translator.llm_client.chat",
      new=AsyncMock(side_effect=_fake_chat(counter, prompts)),
    ):
      res = client.post(
        f"/api/workspaces/{ws_id}/literatures/{lit_id}/translate",
        headers=headers,
        json={"stream": False, "force": True},
      )
      assert res.status_code == 200, res.text
      assert res.json()["status"] == "done"

    # 越权访问其他用户工作空间应 404
    other = client.post(
      "/api/auth/register",
      json={"username": f"transapi_b_{suffix}", "password": "test123456"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['token']}"}
    denied = client.get(
      f"/api/workspaces/{ws_id}/literatures/{lit_id}/translation", headers=other_headers
    )
    assert denied.status_code == 404



@pytest.mark.asyncio
async def test_translate_preserves_caption_and_exposes_warnings():
  from backend.literature.translator import translate_literature

  text = (
    "Introduction\n\n"
    "We propose a model.\n\n"
    "Figure 1. Overall architecture.\n\n"
    "Results follow.\n"
  )
  lit = _make_literature(full_text=text)
  counter: dict = {}
  prompts: list[str] = []

  with patch(
    "backend.literature.translator.llm_client.chat",
    new=AsyncMock(side_effect=_fake_chat(counter, prompts)),
  ):
    result = await translate_literature(lit["literature_id"], max_chars=4000)

  caption_blocks = [b for b in result["blocks"] if b.get("role") == "caption"]
  assert len(caption_blocks) == 1
  assert caption_blocks[0]["content"] == "Figure 1. Overall architecture."
  assert caption_blocks[0]["translation"].strip()
  assert "Figure 1. Overall architecture." in result["markdown"]
  assert result["figure_total"] >= 1
  assert isinstance(result["warnings"], list)
  assert "上一段译文" in prompts[0]


@pytest.mark.asyncio
async def test_translate_skips_references_section():
  from backend.literature.translator import translate_literature

  text = (
    "Introduction\n\n"
    "We propose a model and cite prior work [1].\n\n"
    "Results\n\n"
    "The accuracy reached 92.3%.\n\n"
    "References\n\n"
    "[1] Smith J. Deep learning for imaging. Nature, 2020.\n"
    "[2] Doe A. Another study. Science, 2021.\n"
  )
  lit = _make_literature(full_text=text)
  counter: dict = {}
  prompts: list[str] = []

  with patch(
    "backend.literature.translator.llm_client.chat",
    new=AsyncMock(side_effect=_fake_chat(counter, prompts)),
  ):
    result = await translate_literature(lit["literature_id"], max_chars=4000)

  reference_blocks = [b for b in result["blocks"] if b["kind"] == "reference"]
  assert len(reference_blocks) == 1
  assert reference_blocks[0]["translation"] == ""
  assert "[1] Smith J." in result["markdown"]
  # 参考文献未消耗模型调用，也未进入任何提示词
  text_blocks = [b for b in result["blocks"] if b["kind"] == "text"]
  assert counter["calls"] == len(text_blocks)
  assert all("Smith J." not in prompt for prompt in prompts)


def test_literature_pdf_endpoint_requires_token_and_reports_missing():
  suffix = uuid.uuid4().hex[:8]
  with TestClient(app) as client:
    registered = client.post(
      "/api/auth/register",
      json={"username": f"pdfapi_{suffix}", "password": "test123456"},
    )
    assert registered.status_code in (200, 201), registered.text
    token = registered.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    user_id = client.get("/api/auth/me", headers=headers).json()["id"]

    lit = _make_literature(user_id=user_id)  # pdf_path 为空
    ws_id, lit_id = lit["workspace_id"], lit["literature_id"]

    # 未携带 token：401
    unauth = client.get(f"/api/workspaces/{ws_id}/literatures/{lit_id}/pdf")
    assert unauth.status_code == 401

    # 文献未上传 PDF：404
    missing = client.get(
      f"/api/workspaces/{ws_id}/literatures/{lit_id}/pdf?token={token}"
    )
    assert missing.status_code == 404
def _slow_chat(counter: dict, prompts: list[str], delay: float = 0.02):
  """模拟较慢的大模型流式返回，便于在中途断开订阅后观察后台任务是否继续"""
  async def fake_chat(messages, **kwargs):
    counter["calls"] = counter.get("calls", 0) + 1
    prompts.append(messages[0]["content"])
    text = f"【第{counter['calls']}段译文】深度学习在医学图像分析中取得了显著成功。"

    async def stream():
      for i in range(0, len(text), 6):
        await asyncio.sleep(delay)
        yield text[i:i + 6]

    return stream()

  return fake_chat


@pytest.mark.asyncio
async def test_background_translation_continues_after_subscriber_leaves():
  """退出文献助手（SSE 订阅断开）后，后台翻译任务继续执行并译完"""
  from backend.literature.translator import (
    get_translation_payload,
    get_translation_run,
    start_translation_run,
  )

  lit = _make_literature()
  lit_id = lit["literature_id"]
  counter: dict = {}
  prompts: list[str] = []

  with patch(
    "backend.literature.translator.llm_client.chat",
    new=AsyncMock(side_effect=_slow_chat(counter, prompts)),
  ):
    run = await start_translation_run(lit_id)
    # 读取两个事件后立即断开订阅（等价于前端退出页面、关闭 SSE 连接）
    subscription = run.subscribe()
    seen: list[str] = []
    try:
      async for event in subscription:
        seen.append(str(event.get("event")))
        if len(seen) >= 2:
          break
    finally:
      await subscription.aclose()

    assert seen[0] == "start"
    # 订阅已断开，但任务仍在后台运行
    assert get_translation_run(lit_id) is not None
    await run.wait()

  payload = get_translation_payload(lit_id)
  assert payload["status"] == "done"
  assert payload["segment_done"] == payload["segment_total"]
  assert payload["markdown"].count("段译文") == payload["segment_total"]
  # 完成后从运行登记表移除，后续请求会重新按已存译文快速返回
  assert get_translation_run(lit_id) is None


@pytest.mark.asyncio
async def test_background_translation_reattach_reads_progress_without_retranslating():
  """离开页面后重新接入：先按已译进度重建状态，再继续实时接收，不重复调用大模型"""
  from backend.literature.translator import (
    DEFAULT_SEGMENT_CHARS,
    get_translation_payload,
    split_for_translation,
    start_translation_run,
  )

  lit = _make_literature()
  lit_id = lit["literature_id"]
  counter: dict = {}
  prompts: list[str] = []

  with patch(
    "backend.literature.translator.llm_client.chat",
    new=AsyncMock(side_effect=_slow_chat(counter, prompts)),
  ):
    run = await start_translation_run(lit_id, glossary="deep learning=深度学习")

    # 发起翻译的页面接入后立刻离开
    first = run.subscribe()
    try:
      async for _event in first:
        break
    finally:
      await first.aclose()

    # 重新打开页面：先收到按数据库重建的 start 快照（含已译进度），再接续实时事件
    second = run.subscribe()
    try:
      snapshot = await second.__anext__()
    finally:
      await second.aclose()

    assert snapshot["event"] == "start"
    expected_segments = len(split_for_translation(ENGLISH_TEXT, DEFAULT_SEGMENT_CHARS))
    assert snapshot["total"] == expected_segments
    assert 0 <= snapshot["done_count"] <= expected_segments
    assert snapshot["resumed"] == (snapshot["done_count"] > 0)

    await run.wait()

  payload = get_translation_payload(lit_id)
  assert payload["status"] == "done"
  assert payload["segment_done"] == payload["segment_total"]
  # 重新接入只是读取进度，不会重复翻译
  assert counter["calls"] == payload["segment_total"]
  assert payload["segment_total"] == expected_segments
  assert "deep learning=深度学习" in prompts[0]


@pytest.mark.asyncio
async def test_start_translation_run_reuses_running_task_and_restarts_on_force():
  from backend.literature.translator import (
    get_translation_payload,
    get_translation_run,
    start_translation_run,
  )

  lit = _make_literature()
  lit_id = lit["literature_id"]
  counter: dict = {}
  prompts: list[str] = []

  with patch(
    "backend.literature.translator.llm_client.chat",
    new=AsyncMock(side_effect=_slow_chat(counter, prompts)),
  ):
    run = await start_translation_run(lit_id)
    # 已有任务在跑：再次请求（force=False）复用同一任务，不重复调用大模型
    assert await start_translation_run(lit_id) is run
    # “重新翻译整篇”：先停掉旧任务，再从头开始
    replaced = await start_translation_run(lit_id, force=True)
    assert replaced is not run
    assert get_translation_run(lit_id) is replaced
    await replaced.wait()

  assert get_translation_run(lit_id) is None
  payload = get_translation_payload(lit_id)
  assert payload["status"] == "done"
  assert payload["segment_done"] == payload["segment_total"]


def test_translate_api_stream_replays_completed_translation_without_extra_calls():
  """已完成后再请求流式接口：只回放结果，不再消耗模型调用"""
  suffix = uuid.uuid4().hex[:8]
  with TestClient(app) as client:
    registered = client.post(
      "/api/auth/register",
      json={"username": f"transbg_{suffix}", "password": "test123456"},
    )
    assert registered.status_code in (200, 201), registered.text
    headers = {"Authorization": f"Bearer {registered.json()['token']}"}
    user_id = client.get("/api/auth/me", headers=headers).json()["id"]

    lit = _make_literature(user_id=user_id)
    ws_id, lit_id = lit["workspace_id"], lit["literature_id"]
    counter: dict = {}
    prompts: list[str] = []
    url = f"/api/workspaces/{ws_id}/literatures/{lit_id}/translate"

    with patch(
      "backend.literature.translator.llm_client.chat",
      new=AsyncMock(side_effect=_fake_chat(counter, prompts)),
    ):
      first = client.post(url, headers=headers, json={"stream": True})
      assert first.status_code == 200, first.text
      assert "event: start" in first.text and "event: done" in first.text
      calls_after_first = counter["calls"]
      assert calls_after_first > 0

      second = client.post(url, headers=headers, json={"stream": True})
      assert second.status_code == 200, second.text
      assert "event: start" in second.text and "event: done" in second.text
      assert counter["calls"] == calls_after_first

  from backend.literature.translator import get_translation_run

  assert get_translation_run(lit_id) is None