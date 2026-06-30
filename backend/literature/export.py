"""引用导出功能"""
import json
import re
import xml.etree.ElementTree as ET
from typing import Literal


def _format_authors_apa(authors: list[str]) -> str:
  if not authors:
    return "Anonymous"
  if len(authors) == 1:
    return authors[0]
  if len(authors) == 2:
    return f"{authors[0]} & {authors[1]}"
  return f"{authors[0]} et al."


def export_bibtex(literatures: list[dict]) -> str:
  entries = []
  for i, lit in enumerate(literatures, 1):
    key = re.sub(r"[^a-zA-Z0-9]", "", lit.get("authors", ["anon"])[0][:8].lower() if lit.get("authors") else "anon")
    key = f"{key}{lit.get('year') or i}"
    authors = " and ".join(lit.get("authors", []))
    entry = f"""@article{{{key},
  title = {{{lit.get('title', '')}}},
  author = {{{authors}}},
  journal = {{{lit.get('journal', '')}}},
  year = {{{lit.get('year') or ''}}},
  doi = {{{lit.get('doi', '')}}}
}}"""
    entries.append(entry)
  return "\n\n".join(entries)


def export_endnote_xml(literatures: list[dict]) -> str:
  root = ET.Element("xml")
  records = ET.SubElement(root, "records")
  for lit in literatures:
    rec = ET.SubElement(records, "record")
    ET.SubElement(rec, "ref-type").text = "17"
    titles = ET.SubElement(rec, "titles")
    ET.SubElement(titles, "title").text = lit.get("title", "")
    ET.SubElement(rec, "secondary-title").text = lit.get("journal", "")
    ET.SubElement(rec, "year").text = str(lit.get("year") or "")
    ET.SubElement(rec, "doi").text = lit.get("doi", "")
    for author in lit.get("authors", []):
      contrib = ET.SubElement(rec, "contributors")
      auth = ET.SubElement(contrib, "authors")
      ET.SubElement(auth, "author").text = author
  return ET.tostring(root, encoding="unicode")


def export_references(
  literatures: list[dict],
  style: Literal["apa", "gbt7714"] = "gbt7714",
) -> str:
  lines = []
  for i, lit in enumerate(literatures, 1):
    authors = lit.get("authors", [])
    title = lit.get("title", "")
    journal = lit.get("journal", "")
    year = lit.get("year", "")
    doi = lit.get("doi", "")

    if style == "apa":
      line = f"[{i}] {_format_authors_apa(authors)} ({year}). {title}. *{journal}*."
      if doi:
        line += f" https://doi.org/{doi}"
    else:
      author_str = ", ".join(authors[:3])
      if len(authors) > 3:
        author_str += ", 等"
      line = f"[{i}] {author_str}. {title}[J]. {journal}, {year}."
      if doi:
        line += f" DOI:{doi}"

    lines.append(line)
  return "\n".join(lines)
