"""文献 PDF 图片提取单元测试"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.literature.images import _safe_image_name, extract_pdf_images


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
