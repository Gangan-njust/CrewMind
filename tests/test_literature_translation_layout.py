"""译文版式布局测试：图表按原文位置内联、表格格式与数据原样保留"""
import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from backend.storage.database import get_session, setup_database
from backend.storage.models import (
  LiteratureAnalysisRecord,
  LiteratureRecord,
  User,
  WorkspaceRecord,
)

PIPE_TABLE = (
  "| Model | Accuracy | F1 |\n"
  "|-------|----------|----|\n"
  "| CNN | 92.3 | 0.91 |\n"
  "| ViT | 94.1 | 0.93 |"
)

ALIGNED_TABLE = (
  "Method      Accuracy   F1\n"
  "CNN         92.3       0.91\n"
  "ViT         94.1       0.93"
)

ENGLISH_TEXT = (
  "Introduction\n\n"
  "Deep learning has achieved remarkable success in medical image analysis.\n\n"
  "Results\n\n"
  f"{PIPE_TABLE}\n\n"
  "The model reached an accuracy of 92.3% [12], outperforming the baseline.\n"
)


@pytest.fixture(scope="module", autouse=True)
def _setup_db():
  setup_database()


def test_detect_table_blocks_finds_pipe_table():
  from backend.literature.translation_layout import detect_table_blocks

  tables = detect_table_blocks(f"Results\n\n{PIPE_TABLE}\n\nDone.")
  assert len(tables) == 1
  assert tables[0]["text"] == PIPE_TABLE
  assert "| CNN | 92.3 | 0.91 |" in tables[0]["text"]


def test_detect_table_blocks_finds_aligned_table():
  from backend.literature.translation_layout import detect_table_blocks

  tables = detect_table_blocks(f"Table 2. Ablation study\n\n{ALIGNED_TABLE}\n")
  assert len(tables) == 1
  assert tables[0]["text"] == ALIGNED_TABLE


def test_detect_table_blocks_ignores_paragraphs_and_toc():
  from backend.literature.translation_layout import detect_table_blocks

  text = (
    "Introduction\n\n"
    "We trained a convolutional neural network on 10,000 labeled images.\n\n"
    "1  Introduction .......... 3\n"
    "2  Methods ............... 7\n"
    "3  Conclusion ............ 21\n"
  )
  assert detect_table_blocks(text) == []



def test_build_layout_blocks_places_figure_next_to_caption():
  from backend.literature.translation_layout import build_layout_blocks

  pages = [
    "Title page of the paper.\n\nAbstract: a study on CNN.",
    "Methods\n\nWe trained a CNN on 10,000 images.\n\nFigure 1. Architecture.",
  ]
  content = "\n\n".join(pages)
  images = [{"filename": "002-fig1.png", "page": 2, "caption": "图 1：模型结构"}]

  with patch(
    "backend.literature.translation_layout.extract_pages_text",
    return_value=pages,
  ):
    blocks = build_layout_blocks(
      content, max_chars=4000, images=images, pdf_path="paper.pdf"
    )

  kinds = [block["kind"] for block in blocks]
  assert kinds.count("figure") == 1
  figure_index = kinds.index("figure")
  # 图片锚定到原文图注，紧随其后是「原文保留」的题注块，位置与原文一致
  assert blocks[figure_index]["filename"] == "002-fig1.png"
  assert blocks[figure_index]["number"] == "1"
  caption_block = blocks[figure_index + 1]
  assert caption_block["kind"] == "text"
  assert caption_block["role"] == "caption"
  assert caption_block["content"] == "Figure 1. Architecture."
  assert "Title page" in blocks[0]["source"]
  assert any("Methods" in block["source"] for block in blocks[:figure_index])


def test_locate_figure_anchors_keeps_document_order_without_pdf():
  from backend.literature.translation_layout import locate_figure_anchors

  content = "\n\n".join(f"Paragraph {i} about deep learning." for i in range(6))
  images = [
    {"filename": "003-fig3.png", "page": 3},
    {"filename": "001-fig1.png", "page": 1},
  ]
  anchors = locate_figure_anchors(content, images, pdf_path="")

  assert [item["filename"] for item in anchors] == ["001-fig1.png", "003-fig3.png"]
  assert anchors[0]["offset"] <= anchors[1]["offset"]


def test_locate_figure_anchors_uses_image_number_without_content_caption():
  from backend.literature.translation_layout import locate_figure_anchors

  # 原文没有空行分隔（PDF 文本常见），题注段落识别不到时仍应带上图号
  content = "Intro text about the pipeline.\n\nFigure 1. Overview.\n\nBody follows."
  images = [{"filename": "001-figure-1.png", "page": 1, "number": "1", "region": True}]
  anchors = locate_figure_anchors(content, images, pdf_path="")
  assert len(anchors) == 1
  assert anchors[0]["number"] == "1"
  assert anchors[0]["filename"] == "001-figure-1.png"


def test_build_layout_blocks_keeps_table_between_text_blocks():
  from backend.literature.translation_layout import build_layout_blocks

  blocks = build_layout_blocks(ENGLISH_TEXT, max_chars=200)
  kinds = [block["kind"] for block in blocks]
  assert kinds.count("table") == 1
  table_index = kinds.index("table")
  assert "Deep learning" in blocks[0]["source"]
  assert blocks[table_index]["content"] == PIPE_TABLE
  assert "outperforming the baseline" in blocks[table_index + 1]["source"]


def test_table_as_markdown_keeps_alignment_in_code_fence():
  from backend.literature.translation_layout import table_as_markdown

  assert table_as_markdown({"text": PIPE_TABLE}) == PIPE_TABLE
  fenced = table_as_markdown({"text": ALIGNED_TABLE})
  assert fenced.startswith("```text\n")
  assert ALIGNED_TABLE in fenced


def _make_literature(
  *,
  full_text: str,
  images: list[dict] | None = None,
  user_id: str | None = None,
) -> dict:
  owner = user_id or str(uuid.uuid4())
  ws_id = str(uuid.uuid4())
  lit_id = str(uuid.uuid4())
  now = datetime.now()
  with get_session() as session:
    if not user_id:
      session.add(User(
        id=owner,
        username=f"layout_{uuid.uuid4().hex[:8]}",
        password_hash="hash",
        created_at=now,
      ))
    session.add(WorkspaceRecord(
      id=ws_id, name="版式测试库", description="", user_id=owner,
      current_selected_ids_json="[]", created_at=now, updated_at=now,
    ))
    session.add(LiteratureRecord(
      id=lit_id, workspace_id=ws_id, title="Deep Learning for Medical Imaging",
      authors_json='["Alice"]', journal="Nature", year=2024, doi="10.1/x",
      abstract="A study on CNN for diagnosis.", pdf_path="", full_text=full_text,
      uploaded_at=now, status="done",
    ))
    if images is not None:
      session.add(LiteratureAnalysisRecord(
        id=str(uuid.uuid4()), literature_id=lit_id,
        images_json=json.dumps(images, ensure_ascii=False),
        created_at=now, updated_at=now,
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


def test_translate_api_streams_block_events_with_layout():
  """SSE 事件需带 block_index / kind / 表格内容 / 图片信息，供译文页按原文位置渲染"""
  from fastapi.testclient import TestClient

  from backend.main import app

  suffix = uuid.uuid4().hex[:8]
  with TestClient(app) as client:
    registered = client.post(
      "/api/auth/register",
      json={"username": f"layoutapi_{suffix}", "password": "test123456"},
    )
    assert registered.status_code in (200, 201), registered.text
    headers = {"Authorization": f"Bearer {registered.json()['token']}"}
    user_id = client.get("/api/auth/me", headers=headers).json()["id"]

    lit = _make_literature(
      full_text=ENGLISH_TEXT,
      images=[{"filename": "001-fig1.png", "page": 1, "caption": "图 1：整体流程"}],
      user_id=user_id,
    )
    ws_id, lit_id = lit["workspace_id"], lit["literature_id"]

    with patch(
      "backend.literature.translator.llm_client.chat",
      new=AsyncMock(side_effect=_fake_chat({}, [])),
    ):
      res = client.post(
        f"/api/workspaces/{ws_id}/literatures/{lit_id}/translate",
        headers=headers,
        json={"stream": True},
      )
      assert res.status_code == 200, res.text
      stream = res.text

      assert '"block_index"' in stream
      assert '"kind": "figure"' in stream
      assert '"filename": "001-fig1.png"' in stream
      assert '"caption": "图 1：整体流程"' in stream
      assert '"kind": "table"' in stream
      assert "| CNN | 92.3 | 0.91 |" in stream

      saved = client.get(
        f"/api/workspaces/{ws_id}/literatures/{lit_id}/translation", headers=headers
      ).json()

    assert saved["layout"] == "blocks-v2"
    assert saved["block_total"] == len(saved["blocks"])
    figure = next(b for b in saved["blocks"] if b["kind"] == "figure")
    assert figure["filename"] == "001-fig1.png"
    table = next(b for b in saved["blocks"] if b["kind"] == "table")
    assert table["content"] == PIPE_TABLE


@pytest.mark.asyncio
async def test_translate_keeps_tables_and_inlines_figures():
  from backend.literature.translator import translate_literature

  lit = _make_literature(
    full_text=ENGLISH_TEXT,
    images=[{"filename": "001-fig1.png", "page": 1, "caption": "图 1：整体流程"}],
  )
  counter: dict = {}
  prompts: list[str] = []

  with patch(
    "backend.literature.translator.llm_client.chat",
    new=AsyncMock(side_effect=_fake_chat(counter, prompts)),
  ):
    result = await translate_literature(lit["literature_id"], max_chars=120)

  assert result["status"] == "done"
  assert result["layout"] == "blocks-v2"
  kinds = [block["kind"] for block in result["blocks"]]
  assert "table" in kinds and "figure" in kinds
  assert result["block_total"] == len(result["blocks"])

  table_block = next(b for b in result["blocks"] if b["kind"] == "table")
  assert table_block["content"] == PIPE_TABLE          # 表格格式与数据零改动
  assert table_block["translation"] == ""
  assert result["markdown"].count("| CNN | 92.3 | 0.91 |") == 1

  figure_block = next(b for b in result["blocks"] if b["kind"] == "figure")
  assert figure_block["filename"] == "001-fig1.png"
  assert figure_block["caption"] == "图 1：整体流程"
  assert "literature-image:001-fig1.png" in result["markdown"]

  # 表格与图片不消耗大模型调用：只翻译文本块，段落总数只统计文本块
  text_blocks = [b for b in result["blocks"] if b["kind"] == "text"]
  assert counter["calls"] == len(text_blocks)
  assert result["segment_total"] == len(text_blocks)
  assert result["segment_done"] == len(text_blocks)
  assert all(block["translation"].strip() for block in text_blocks)
  assert "表格原样" in prompts[0]
  assert "图表位置" in prompts[0]



def test_parse_caption_accepts_captions_and_rejects_references():
  from backend.literature.translation_layout import parse_caption

  assert parse_caption("Figure 1. Architecture of the model.")["number"] == "1"
  assert parse_caption("Fig. 2: Results")["caption_kind"] == "figure"
  assert parse_caption("TABLE 3 Ablation study")["caption_kind"] == "table"
  assert parse_caption("图 4：整体流程图")["number"] == "4"
  assert parse_caption("Table 2 lists the results.") is None
  assert parse_caption("Figure 3 shows the pipeline.") is None
  assert parse_caption("Figures 1 and 2 show results.") is None


def test_figure_caption_number_rejects_inline_references():
  from backend.literature.translation_layout import figure_caption_number

  assert figure_caption_number("Figure 2. Overview of MedSAM-3.") == "2"
  assert figure_caption_number("Fig. 3: Results") == "3"
  assert figure_caption_number("图 4 整体流程") == "4"
  # 正文中的交叉引用不是题注
  assert figure_caption_number("Figure 3 shows the pipeline.") is None
  assert figure_caption_number("Figure 6 also visually illustrates the results.") is None
  assert figure_caption_number("Table 1. The phrase inputs.") is None
  # 无分隔符的题注样式（部分期刊）仍应识别，避免漏图
  assert figure_caption_number("Figure 5 Overview of the proposed framework") == "5"


def test_build_layout_blocks_keeps_caption_verbatim():
  from backend.literature.translation_layout import build_layout_blocks

  text = "Intro text.\n\nFigure 1. The framework.\n\nBody follows."
  blocks = build_layout_blocks(text, max_chars=4000)
  captions = [block for block in blocks if block.get("role") == "caption"]
  assert len(captions) == 1
  assert captions[0]["content"] == "Figure 1. The framework."
  assert captions[0]["source"] == "Figure 1. The framework."


def test_build_layout_blocks_creates_placeholder_for_missing_figure():
  from backend.literature.translation_layout import build_layout_blocks

  text = "Intro.\n\nFigure 2. Vector diagram.\n\nMore text."
  blocks = build_layout_blocks(text, images=[], pdf_path="")
  figures = [block for block in blocks if block["kind"] == "figure"]
  assert len(figures) == 1
  assert figures[0]["placeholder"] is True
  assert figures[0]["filename"] == ""
  assert figures[0]["number"] == "2"


def test_layout_reference_stats_reports_missing_tables():
  from backend.literature.translation_layout import (
    build_layout_blocks,
    layout_reference_stats,
    seal_blocks,
  )

  text = "Intro.\n\nTable 1. Results\n\nNo table body here.\n\nTable 2. More\n\nstill text."
  sealed = seal_blocks(build_layout_blocks(text, images=[], pdf_path=""))
  stats = layout_reference_stats(text, sealed)
  assert "1" in stats["table_refs"]
  assert stats["missing_tables"]
  assert stats["warnings"]


def test_table_caption_number_attached_to_table_block():
  from backend.literature.translation_layout import build_layout_blocks

  text = "Results\n\nTable 1. Metrics\n\n| Model | Acc |\n|-------|-----|\n| CNN | 92.3 |\n"
  blocks = build_layout_blocks(text, max_chars=4000)
  table = next(block for block in blocks if block["kind"] == "table")
  assert table["content"] == "| Model | Acc |\n|-------|-----|\n| CNN | 92.3 |"
  assert table["number"] == "1"


def test_seal_blocks_keeps_source_for_compare_view():
  from backend.literature.translation_layout import build_layout_blocks, seal_blocks

  text = (
    "Intro paragraph about the method.\n\n"
    "Figure 1. Overview of the pipeline.\n\n"
    "Table 1. Metrics\n\n"
    "| Model | Acc |\n|-------|-----|\n| CNN | 92.3 |\n"
  )
  sealed = seal_blocks(build_layout_blocks(text, images=[], pdf_path=""))
  text_blocks = [block for block in sealed if block["kind"] == "text"]
  assert text_blocks
  # 正文块与题注块都保留英文原文，供左右对照阅读
  assert all(block["source"] for block in text_blocks)
  caption = next(block for block in text_blocks if block["role"] == "caption")
  assert caption["content"] == "Figure 1. Overview of the pipeline."
  assert caption["source"] == "Figure 1. Overview of the pipeline."
  assert "Intro paragraph" in text_blocks[0]["source"]


def test_reference_section_is_kept_untranslated():
  from backend.literature.translation_layout import BLOCK_KIND_REFERENCE, build_layout_blocks

  text = (
    "Introduction\n\n"
    "We propose a model and cite prior work [1].\n\n"
    "Results\n\n"
    "The accuracy reached 92.3%.\n\n"
    "References\n\n"
    "[1] Smith J. Deep learning for imaging. Nature, 2020.\n"
    "[2] Doe A. Another study. Science, 2021.\n"
  )
  blocks = build_layout_blocks(text, images=[], pdf_path="")
  references = [block for block in blocks if block["kind"] == BLOCK_KIND_REFERENCE]
  assert len(references) == 1
  assert "[1] Smith J." in references[0]["content"]
  assert references[0]["char_start"] > 0
  body = " ".join(block.get("source", "") for block in blocks if block["kind"] == "text")
  assert "Smith J." not in body


def test_detect_reference_section_ignores_early_and_inline_mentions():
  from backend.literature.translation_layout import detect_reference_section_start

  early = "References\n\n" + "Body text. " * 60
  assert detect_reference_section_start(early) is None

  inline = "Body text. " * 40 + "\n\nSee References for details.\n\nTail. " * 1
  assert detect_reference_section_start(inline) is None

  tail = "Body text. " * 40 + "\n\nReferences\n\n[1] Smith J. 2020.\n"
  start = detect_reference_section_start(tail)
  assert start is not None and tail[start:].startswith("References")
