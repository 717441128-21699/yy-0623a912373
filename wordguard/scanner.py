import os
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime


SUPPORTED_EXTENSIONS = {".md", ".txt", ".markdown", ".text"}


def count_chinese_chars(text: str) -> int:
    return len(re.findall(r'[\u4e00-\u9fff]', text))


def count_english_words(text: str) -> int:
    words = re.findall(r'[a-zA-Z]+', text)
    return len(words)


def count_words(text: str) -> int:
    chinese = count_chinese_chars(text)
    english = count_english_words(text)
    return chinese + english


def strip_markdown(text: str) -> str:
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`[^`]*`', '', text)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[>\-\*\+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}(.*?)_{1,3}', r'\1', text)
    return text


def read_file(file_path: Path) -> Optional[str]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except (UnicodeDecodeError, IOError):
        try:
            with open(file_path, "r", encoding="gbk") as f:
                return f.read()
        except IOError:
            return None


def extract_title(text: str, file_name: str) -> str:
    lines = text.splitlines()
    for line in lines[:10]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('#'):
            stripped = stripped.lstrip('#').strip()
        if stripped:
            return stripped
    return Path(file_name).stem


def extract_author_note(text: str) -> Optional[str]:
    patterns = [
        r'作者有话说[:：]?\s*\n([\s\S]*?)(?=\n\s*\n|\Z)',
        r'作者说[:：]?\s*\n([\s\S]*?)(?=\n\s*\n|\Z)',
        r'PS[:：]?\s*\n([\s\S]*?)(?=\n\s*\n|\Z)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            note = match.group(1).strip()
            if note:
                return note
    return None


def extract_last_paragraphs(text: str, num: int = 3) -> List[str]:
    text = strip_markdown(text)
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    return paragraphs[-num:] if paragraphs else []


def extract_cliffhanger_cues(text: str) -> List[str]:
    last_paragraphs = extract_last_paragraphs(text, 5)
    cues = []
    keywords = ['忽然', '突然', '竟然', '居然', '只见', '却见', '谁知', '不料',
                '就在这时', '正在此时', '下一刻', '下一秒', '猛地', '赫然',
                '心中一凛', '脸色一变', '瞳孔骤缩', '倒吸一口凉气']
    for para in last_paragraphs:
        for kw in keywords:
            if kw in para:
                cues.append(para[:100] + ('...' if len(para) > 100 else ''))
                break
    return cues


def scan_chapter(file_path: Path) -> Optional[Dict]:
    raw_text = read_file(file_path)
    if raw_text is None:
        return None
    clean_text = strip_markdown(raw_text)
    word_count = count_words(clean_text)
    title = extract_title(raw_text, file_path.name)
    author_note = extract_author_note(raw_text)
    cliffhangers = extract_cliffhanger_cues(raw_text)

    return {
        "file_path": str(file_path),
        "file_name": file_path.name,
        "title": title,
        "word_count": word_count,
        "chinese_chars": count_chinese_chars(clean_text),
        "english_words": count_english_words(clean_text),
        "author_note": author_note,
        "has_author_note": author_note is not None,
        "cliffhanger_cues": cliffhangers,
        "last_paragraphs": extract_last_paragraphs(raw_text, 3),
        "modified_time": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
        "size_bytes": file_path.stat().st_size,
    }


def scan_draft_dir(draft_dir: str) -> List[Dict]:
    draft_path = Path(draft_dir)
    if not draft_path.exists() or not draft_path.is_dir():
        return []

    chapters = []
    for ext in SUPPORTED_EXTENSIONS:
        for file_path in draft_path.rglob(f"*{ext}"):
            if file_path.is_file():
                chapter = scan_chapter(file_path)
                if chapter:
                    chapters.append(chapter)

    chapters.sort(key=lambda c: c["file_name"])

    published = []
    drafts = []
    for ch in chapters:
        name = ch["file_name"].lower()
        if any(tag in name for tag in ["draft", "草稿", "未发布", "存稿", "todo", "待发"]):
            drafts.append(ch)
        else:
            published.append(ch)

    if not drafts:
        if len(published) >= 2:
            drafts = [published[-1]]
            published = published[:-1]

    return {
        "all": chapters,
        "published": sorted(published, key=lambda c: c["file_name"]),
        "drafts": sorted(drafts, key=lambda c: c["file_name"]),
    }


def get_chapter_word_delta(chapter: Dict) -> Tuple[int, int]:
    from .config import get_chapter_snapshot
    snapshot = get_chapter_snapshot(chapter["title"])
    previous = snapshot["word_count"] if snapshot else 0
    delta = chapter["word_count"] - previous
    return delta, previous


def classify_chapter_status(chapter: Dict, publish_line_words: int) -> str:
    wc = chapter["word_count"]
    if wc >= publish_line_words:
        return "ready"
    elif wc >= publish_line_words * 0.5:
        return "writing"
    else:
        return "outline"
