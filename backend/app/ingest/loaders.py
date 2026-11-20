"""Turn files on disk into plain text, page by page."""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

SUPPORTED = {".pdf", ".md", ".markdown", ".txt"}


@dataclass
class Page:
    number: int  # 1-based
    text: str


@dataclass
class LoadedDocument:
    doc_id: str
    title: str
    source: str  # file name
    pages: list[Page] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # re-join hyphenated line breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_BOILERPLATE = re.compile(
    r"^(arxiv|http|preprint|published as|under review|accepted|proceedings|workshop|"
    r"technical report|copyright|\d{4}\b)",
    re.IGNORECASE,
)
# A title line ending in one of these continues on the next line.
_DANGLING = re.compile(r"(\b(for|of|to|and|in|on|with|via|a|an|the)|[:,-])$", re.IGNORECASE)


def _guess_title(text: str, fallback: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, line in enumerate(lines[:15]):
        if len(line) < 8 or len(line) > 150 or _BOILERPLATE.match(line):
            continue
        title = line
        j = i + 1
        while _DANGLING.search(title) and j < len(lines) and len(lines[j]) <= 100:
            title = f"{title} {lines[j]}"
            j += 1
        return title.rstrip(" .")
    return fallback


def load_file(path: Path) -> LoadedDocument:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"Unsupported file type '{suffix}'. Supported: {sorted(SUPPORTED)}")

    raw = path.read_bytes()
    doc_id = hashlib.sha1(raw).hexdigest()[:16]

    if suffix == ".pdf":
        reader = PdfReader(path)
        pages = [
            Page(number=i + 1, text=_clean(page.extract_text() or ""))
            for i, page in enumerate(reader.pages)
        ]
        pages = [p for p in pages if p.text]
        meta_title = ((reader.metadata.title if reader.metadata else None) or "").strip()
        # PDF metadata titles are often junk ("Microsoft Word - draft3.docx"); trust only plausible ones.
        plausible = len(meta_title) > 10 and " " in meta_title and not meta_title.lower().endswith((".doc", ".docx", ".tex", ".pdf"))
        title = meta_title if plausible else ""
    else:
        text = _clean(raw.decode("utf-8", errors="replace"))
        pages = [Page(number=1, text=text)] if text else []
        heading = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
        title = heading.group(1).strip() if heading else ""

    if not pages:
        raise ValueError(f"No extractable text in {path.name} (scanned PDF?)")

    title = title or _guess_title(pages[0].text, path.stem)
    return LoadedDocument(doc_id=doc_id, title=title, source=path.name, pages=pages)
