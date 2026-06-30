import pytest

from backend.writing.assistant import polish_text_structured


@pytest.mark.asyncio
async def test_polish_text_structured_requires_enabled_items():
  with pytest.raises(ValueError, match="至少启用"):
    await polish_text_structured(
      "",
      section_type="intro",
      items=[],
    )

  with pytest.raises(ValueError, match="至少启用"):
    await polish_text_structured(
      "",
      section_type="intro",
      items=[{"title": "背景", "level": 2, "enabled": False}],
    )
