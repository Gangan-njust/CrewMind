"""RAG 分块单元测试"""
import uuid

from backend.rag.chunker import chunk_literature, compute_document_hash


def test_abstract_as_separate_chunk():
  lit_id = str(uuid.uuid4())
  ws_id = str(uuid.uuid4())
  abstract = "这是摘要内容，描述研究目标与方法。"
  full_text = "Introduction\n\nThis paper presents a novel approach."

  chunks = chunk_literature(lit_id, ws_id, full_text, abstract, chunk_size=600, chunk_overlap=120)

  assert len(chunks) >= 2
  assert chunks[0].section_key == "abstract"
  assert chunks[0].content == abstract
  assert chunks[0].literature_id == lit_id


def test_section_sliding_window_respects_paragraphs():
  lit_id = str(uuid.uuid4())
  ws_id = str(uuid.uuid4())
  para_a = "A" * 200
  para_b = "B" * 200
  para_c = "C" * 200
  full_text = f"METHODS\n\n{para_a}\n\n{para_b}\n\n{para_c}"

  chunks = chunk_literature(lit_id, ws_id, full_text, chunk_size=350, chunk_overlap=50)

  methods_chunks = [c for c in chunks if c.section_key == "methods"]
  assert len(methods_chunks) >= 2
  for c in methods_chunks:
    assert c.content
    assert c.char_end > c.char_start


def test_compute_document_hash_changes_with_content():
  h1 = compute_document_hash("text one", "abstract")
  h2 = compute_document_hash("text two", "abstract")
  h3 = compute_document_hash("text one", "abstract changed")
  assert h1 != h2
  assert h1 != h3
  assert h1 == compute_document_hash("text one", "abstract")
