"""文献 PDF 图片提取单元测试"""
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from backend.literature.images import (
  _safe_image_name,
  extract_pdf_images,
  render_figure_regions,
)


class FakeImage:
  def __init__(self, name: str, data: bytes, size=(100, 50)):
    self.name = name
    self.data = data
    self.image = MagicMock()
    self.image.size = size


class FakePage:
  def __init__(self, images: list[FakeImage], text: str = ""):
    self._images = images
    self._text = text

  @property
  def images(self):
    return self._images

  def extract_text(self) -> str:
    return self._text


@pytest.fixture
def fake_reader():
  img1 = FakeImage("fig1.png", b"x" * 5000, (640, 480))
  img2 = FakeImage("fig2.jpg", b"y" * 5000, (300, 200))
  dup = FakeImage("fig1-copy.png", b"x" * 5000, (640, 480))  # 与 fig1 内容相同
  tiny = FakeImage("logo.png", b"z" * 100, (16, 16))  # 体积过小 -> 过滤
  page_text = "Figure 3. Performance comparison across datasets."
  reader = MagicMock()
  reader.pages = [
    FakePage([img1, img2, dup, tiny], text=page_text),
    FakePage([], text="References"),
  ]
  return reader


def test_safe_image_name():
  assert _safe_image_name("../fig 1.png", 1, ".png") == "001-fig 1.png"
  assert _safe_image_name("", 2, ".jpg") == "002-image.jpg"


def test_extract_pdf_images_writes_and_dedupes(tmp_path: Path, fake_reader):
  out_dir = tmp_path / "images"
  out_dir.mkdir(parents=True, exist_ok=True)
  pdf_file = tmp_path / "paper.pdf"
  pdf_file.write_bytes(b"%PDF-1.7 fake")
  with patch("backend.literature.images.PdfReader", return_value=fake_reader):
    with patch("backend.literature.images.resolve_pdf_path", return_value=pdf_file):
      with patch(
        "backend.literature.images.image_storage_dir",
        return_value=out_dir,
      ):
        out = extract_pdf_images(str(pdf_file), "ws-1", "lit-1")

  assert len(out) == 2  # fig1 + fig2（去重后），tiny 被过滤
  names = [img["filename"] for img in out]
  assert "001-fig1.png" in names
  assert any(n.startswith("002-") for n in names)
  assert (out_dir / "001-fig1.png").exists()
  assert (out_dir / names[1]).exists()
  assert out[0]["page"] == 1
  assert out[0]["width"] == 640
  assert "Performance comparison" in out[0]["context"]


def test_extract_pdf_images_missing_pdf(tmp_path: Path):
  out = extract_pdf_images(tmp_path / "not-exists.pdf", "ws-1", "lit-1")
  assert out == []
# ── 整幅图区域渲染（复合图不拆分） ────────────────────────────

def _build_composite_pdf(path: Path, caption: str) -> None:
  """构造一页：由多个矢量流程框 + 连接件 + 位图 + 文字标签拼成的复合图"""
  fitz = pytest.importorskip("fitz")
  doc = fitz.open()
  page = doc.new_page(width=595, height=842)
  for index in range(6):
    page.draw_rect(
      fitz.Rect(60 + index * 55, 80, 110 + index * 55, 150),
      color=(0.2, 0.4, 0.8),
      width=1,
    )
  page.insert_text((66, 105), "Encoder", fontsize=9)
  page.insert_text((66, 125), "Decoder", fontsize=9)
  # 连接件：把左侧流程框与右侧位图聚成同一幅图
  page.draw_rect(fitz.Rect(386, 105, 419, 112), color=(0, 0, 0), width=1)
  buffer = io.BytesIO()
  Image.new("RGB", (64, 64), (200, 30, 30)).save(buffer, format="PNG")
  page.insert_image(fitz.Rect(420, 72, 500, 152), stream=buffer.getvalue())
  page.insert_textbox(fitz.Rect(60, 190, 540, 230), caption, fontsize=10)
  doc.save(str(path))
  doc.close()


@pytest.fixture
def region_pdf(tmp_path: Path) -> Path:
  pdf_file = tmp_path / "composite.pdf"
  _build_composite_pdf(pdf_file, "Figure 1. Composite pipeline of the model.")
  return pdf_file


def test_render_figure_regions_keeps_composite_figure_whole(region_pdf: Path, tmp_path: Path):
  out_dir = tmp_path / "images"
  out_dir.mkdir(parents=True, exist_ok=True)
  with patch("backend.literature.images.resolve_pdf_path", return_value=region_pdf):
    with patch("backend.literature.images.image_storage_dir", return_value=out_dir):
      regions = render_figure_regions(str(region_pdf), "ws-1", "lit-1")

  # 整幅复合图只产出一张图片，而不是多个组件图
  assert len(regions) == 1
  region = regions[0]
  assert region["page"] == 1
  assert region["number"] == "1"
  assert region["region"] is True
  assert (out_dir / region["filename"]).exists()
  # 渲染宽度覆盖整幅图（单个流程框约 139px 宽，整幅复合图约 1240px）
  assert region["width"] > 900
  assert region["width"] > region["height"]


def test_render_figure_regions_ignores_table_and_inline_reference(tmp_path: Path):
  out_dir = tmp_path / "images"
  out_dir.mkdir(parents=True, exist_ok=True)
  pdf_file = tmp_path / "table.pdf"
  _build_composite_pdf(pdf_file, "Table 1. The phrase inputs used for different datasets.")
  with patch("backend.literature.images.resolve_pdf_path", return_value=pdf_file):
    with patch("backend.literature.images.image_storage_dir", return_value=out_dir):
      assert render_figure_regions(str(pdf_file), "ws-1", "lit-1") == []

  inline_pdf = tmp_path / "inline.pdf"
  _build_composite_pdf(
    inline_pdf,
    "Figure 6 also visually illustrates the substantial performance differences.",
  )
  with patch("backend.literature.images.resolve_pdf_path", return_value=inline_pdf):
    with patch("backend.literature.images.image_storage_dir", return_value=out_dir):
      assert render_figure_regions(str(inline_pdf), "ws-1", "lit-1") == []


def test_render_figure_regions_reuses_manifest(region_pdf: Path, tmp_path: Path):
  out_dir = tmp_path / "images"
  out_dir.mkdir(parents=True, exist_ok=True)
  with patch("backend.literature.images.resolve_pdf_path", return_value=region_pdf):
    with patch("backend.literature.images.image_storage_dir", return_value=out_dir):
      first = render_figure_regions(str(region_pdf), "ws-1", "lit-1")
      assert (out_dir / "figure_regions.json").exists()
      # 第二次调用直接命中缓存，不重新渲染
      with patch("backend.literature.images._page_figure_regions") as page_regions:
        second = render_figure_regions(str(region_pdf), "ws-1", "lit-1")
      page_regions.assert_not_called()
  assert first == second


def test_render_figure_regions_missing_pdf(tmp_path: Path):
  assert render_figure_regions(tmp_path / "not-exists.pdf", "ws-1", "lit-1") == []


def test_load_layout_images_prefers_whole_figure_regions(monkeypatch):
  from backend.literature import translator

  monkeypatch.setattr(
    translator,
    "_load_literature_images",
    lambda *args, **kwargs: [
      {"filename": "001-X8.png", "page": 4},
      {"filename": "002-X9.png", "page": 4},
      {"filename": "003-Im4.png", "page": 9},
    ],
  )
  monkeypatch.setattr(
    "backend.literature.images.render_figure_regions",
    lambda *args, **kwargs: [
      {"filename": "001-figure-2.png", "page": 4, "number": "2", "region": True},
    ],
  )
  images = translator._load_layout_images(
    "lit-1", {"pdf_path": "paper.pdf", "workspace_id": "ws-1"}
  )
  # 第 4 页已整幅渲染，该页的位图碎片不再单独出现；其他页保持原样
  assert [img["filename"] for img in images] == ["001-figure-2.png", "003-Im4.png"]


def test_load_layout_images_falls_back_to_fragments(monkeypatch):
  from backend.literature import translator

  fragments = [{"filename": "001-X8.png", "page": 4}]
  monkeypatch.setattr(translator, "_load_literature_images", lambda *args, **kwargs: fragments)

  # 无 PDF：不渲染区域
  assert translator._load_layout_images("lit-1", {}) == fragments

  # 有 PDF 但未渲染出区域：回退为逐图提取结果
  monkeypatch.setattr(
    "backend.literature.images.render_figure_regions",
    lambda *args, **kwargs: [],
  )
  meta = {"pdf_path": "paper.pdf", "workspace_id": "ws-1"}
  assert translator._load_layout_images("lit-1", meta) == fragments

  # 渲染异常：同样回退，不影响翻译
  def _boom(*args, **kwargs):
    raise RuntimeError("render failed")

  monkeypatch.setattr("backend.literature.images.render_figure_regions", _boom)
  assert translator._load_layout_images("lit-1", meta) == fragments