"""语义辅助切块单元测试：embedding 相似度优化段落合并决策"""
import uuid

from backend.rag.chunker import chunk_literature, _cosine_similarity


class FakeEmbedder:
  """按段落文本映射到向量的假 embedder，便于精确控制相似度"""

  def __init__(self, mapping: dict[str, list[float]]):
    self._mapping = mapping
    self.calls = 0

  def embed(self, texts: list[str]) -> list[list[float]]:
    self.calls += 1
    return [self._mapping[t] for t in texts]


def _chunk_texts(chunks) -> list[str]:
  return [c.content for c in chunks]


def test_cosine_similarity_basic():
  assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
  assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
  assert _cosine_similarity([1.0, 0.0], []) == 0.0
  assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_semantic_off_does_not_call_embedder():
  lit_id = str(uuid.uuid4())
  ws_id = str(uuid.uuid4())
  embedder = FakeEmbedder({})

  chunks = chunk_literature(
    lit_id, ws_id, "A" * 100, "", chunk_size=600, chunk_overlap=120,
    semantic=False, embedder=embedder,
  )
  assert chunks
  assert embedder.calls == 0


def test_semantic_merges_highly_similar_paragraphs():
  """语义相近段落允许超限合并，chunk 数应少于纯规则模式"""
  lit_id = str(uuid.uuid4())
  ws_id = str(uuid.uuid4())
  para_a = "A" * 200
  para_b = "B" * 200
  para_c = "C" * 200
  full_text = f"{para_a}\n\n{para_b}\n\n{para_c}"

  same_vec = [1.0, 0.0, 0.0]
  embedder = FakeEmbedder({para_a: same_vec, para_b: same_vec, para_c: same_vec})

  rule = chunk_literature(
    lit_id, ws_id, full_text, "", chunk_size=350, chunk_overlap=50,
  )
  semantic = chunk_literature(
    lit_id, ws_id, full_text, "", chunk_size=350, chunk_overlap=50,
    semantic=True, embedder=embedder,
  )

  assert embedder.calls == 1
  assert len(semantic) < len(rule)
  # 语义相近的两段被完整合并进同一块
  assert any(para_a in c.content and para_b in c.content for c in semantic)
  assert semantic[0].section_key == "full"


def test_semantic_force_splits_dissimilar_paragraphs():
  """语义突降段落即使长度有余量也强制切分"""
  lit_id = str(uuid.uuid4())
  ws_id = str(uuid.uuid4())
  para_a = "A" * 50
  para_b = "B" * 50
  para_c = "C" * 50
  full_text = f"{para_a}\n\n{para_b}\n\n{para_c}"

  embedder = FakeEmbedder({
    para_a: [1.0, 0.0, 0.0],
    para_b: [0.0, 1.0, 0.0],
    para_c: [0.0, 0.0, 1.0],
  })

  rule = chunk_literature(
    lit_id, ws_id, full_text, "", chunk_size=350, chunk_overlap=120,
  )
  semantic = chunk_literature(
    lit_id, ws_id, full_text, "", chunk_size=350, chunk_overlap=120,
    semantic=True, embedder=embedder,
  )

  # 规则模式三段合并为 1 块；语义模式按突降点切成 3 块
  assert len(rule) == 1
  assert len(semantic) == 3
  assert [c.content for c in semantic] == [para_a, para_b, para_c]


def test_semantic_fallback_on_embedder_error():
  """embedding 计算失败时自动回退为纯规则切块，结果一致"""
  lit_id = str(uuid.uuid4())
  ws_id = str(uuid.uuid4())
  para_a = "A" * 200
  para_b = "B" * 200
  full_text = f"{para_a}\n\n{para_b}"

  class BrokenEmbedder:
    def embed(self, texts):
      raise RuntimeError("model unavailable")

  rule = chunk_literature(
    lit_id, ws_id, full_text, "", chunk_size=350, chunk_overlap=50,
  )
  semantic = chunk_literature(
    lit_id, ws_id, full_text, "", chunk_size=350, chunk_overlap=50,
    semantic=True, embedder=BrokenEmbedder(),
  )

  assert _chunk_texts(semantic) == _chunk_texts(rule)


def test_semantic_keeps_abstract_unchanged():
  """语义模式不影响摘要单独成块"""
  lit_id = str(uuid.uuid4())
  ws_id = str(uuid.uuid4())
  abstract = "这是摘要内容。"
  full_text = "A" * 100

  chunks = chunk_literature(
    lit_id, ws_id, full_text, abstract, chunk_size=600, chunk_overlap=120,
    semantic=True,
    embedder=FakeEmbedder({"A" * 100: [1.0, 0.0]}),
  )
  assert chunks[0].section_key == "abstract"
  assert chunks[0].content == abstract
