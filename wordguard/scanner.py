import os
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime


SUPPORTED_EXTENSIONS = {".md", ".txt", ".markdown", ".text"}


CLIFFHANGER_KEYWORDS = [
    '忽然', '突然', '竟然', '居然', '只见', '却见', '谁知', '不料',
    '就在这时', '正在此时', '下一刻', '下一秒', '猛地', '赫然',
    '心中一凛', '脸色一变', '瞳孔骤缩', '倒吸一口凉气', '大吃一惊',
    '暗叫不好', '心头巨震', '如遭雷击', '毛骨悚然', '不寒而栗',
    '话音未落', '话未说完', '一声巨响', '轰然', '骤然', '蓦然',
    '这时', '就在此时', '恰在此时', '偏偏', '然而', '但',
    '脸色煞白', '浑身一震', '背后发凉', '冷汗直冒',
]


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
    """识别作者有话说，支持同行(:)或下一行开头，支持多种写法。"""
    patterns = [
        r'作者有话说\s*[:：]?\s*\n?([\s\S]*?)(?=\n\s*\n|\Z)',
        r'作者说\s*[:：]?\s*\n?([\s\S]*?)(?=\n\s*\n|\Z)',
        r'作者的话\s*[:：]?\s*\n?([\s\S]*?)(?=\n\s*\n|\Z)',
        r'作者闲话\s*[:：]?\s*\n?([\s\S]*?)(?=\n\s*\n|\Z)',
        r'PS\s*[:：]?\s*\n?([\s\S]*?)(?=\n\s*\n|\Z)',
        r'（作者[:：].*?）',
        r'\(作者[:：].*?\)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            note = match.group(1).strip() if match.lastindex else match.group(0).strip()
            if note and len(note) >= 2:
                return note
    return None


def extract_head_paragraphs(text: str, num: int = 3, char_limit: int = 1500) -> List[str]:
    """提取文章开头的几段，用于悬念衔接检查。"""
    clean = strip_markdown(text)
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', clean) if p.strip()]
    # 过滤太短或只是标题的
    paragraphs = [p for p in paragraphs if len(p) > 10]
    head = []
    total = 0
    for p in paragraphs[:max(num * 2, 6)]:
        if total >= char_limit:
            break
        head.append(p)
        total += len(p)
        if len(head) >= num:
            break
    return head


def extract_last_paragraphs(text: str, num: int = 3, char_limit: int = 1200) -> List[str]:
    """提取文章末尾几段。"""
    clean = strip_markdown(text)
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', clean) if p.strip()]
    paragraphs = [p for p in paragraphs if len(p) > 10]
    tail = []
    total = 0
    for p in reversed(paragraphs):
        if total >= char_limit:
            break
        tail.insert(0, p)
        total += len(p)
        if len(tail) >= num:
            break
    return tail


def extract_cliffhanger_details(text: str) -> List[Dict[str, Any]]:
    """提取悬念详细信息：包含关键词的整句 + 关键词列表。"""
    tail_paragraphs = extract_last_paragraphs(text, 6, 1800)
    details = []
    for para in tail_paragraphs:
        # 拆成句子
        sentences = re.split(r'[。！？!?。\n]', para)
        for sent in sentences:
            sent = sent.strip()
            if not sent or len(sent) < 5:
                continue
            found_kw = [kw for kw in CLIFFHANGER_KEYWORDS if kw in sent]
            if found_kw:
                details.append({
                    "sentence": sent[:120] + ('...' if len(sent) > 120 else ''),
                    "keywords": found_kw,
                    "paragraph_excerpt": para[:100] + ('...' if len(para) > 100 else ''),
                })
    # 去重并按长度排序
    seen = set()
    unique = []
    for d in details:
        k = d["sentence"][:40]
        if k not in seen:
            seen.add(k)
            unique.append(d)
    return sorted(unique, key=lambda d: -len(d["keywords"]))


def check_cliffhanger_connection(prev_chapter: Dict, next_chapter: Dict) -> Dict[str, Any]:
    """检查上一章悬念和本章开头的衔接情况。返回详细匹配信息。"""
    result = {
        "connected": False,
        "match_count": 0,
        "prev_cliffhangers": [],
        "matched_hits": [],
        "next_head_excerpt": "",
    }

    prev_cliffhangers = prev_chapter.get("cliffhanger_details") or extract_cliffhanger_details(
        read_file(Path(prev_chapter["file_path"])) or ""
    )
    result["prev_cliffhangers"] = prev_cliffhangers[:3]

    if not prev_cliffhangers:
        result["connected"] = True
        result["note"] = "上一章未检测到悬念措辞，默认衔接"
        return result

    next_text = read_file(Path(next_chapter["file_path"])) or ""
    next_head = "\n".join(extract_head_paragraphs(next_text, 4, 2000))
    result["next_head_excerpt"] = next_head[:200] + ('...' if len(next_head) > 200 else '')

    matched_hits = []
    for ch in prev_cliffhangers[:3]:
        for kw in ch["keywords"]:
            # 看关键词或其核心词是否在本章开头出现
            core_words = [kw[i:i+2] for i in range(len(kw) - 1)] if len(kw) >= 2 else [kw]
            for cw in core_words:
                if cw in next_head:
                    # 找到具体出现的位置，取前后上下文
                    idx = next_head.find(cw)
                    start = max(0, idx - 12)
                    end = min(len(next_head), idx + len(cw) + 12)
                    context = next_head[start:end]
                    matched_hits.append({
                        "prev_keyword": kw,
                        "matched_subword": cw,
                        "next_context": ('...' if start > 0 else '') + context + ('...' if end < len(next_head) else ''),
                    })
                    break
    if matched_hits:
        # 去重
        dedup = {}
        for m in matched_hits:
            key = m["prev_keyword"] + "|" + m["matched_subword"]
            if key not in dedup:
                dedup[key] = m
        unique_matches = list(dedup.values())
        result["connected"] = len(unique_matches) >= 1
        result["match_count"] = len(unique_matches)
        result["matched_hits"] = unique_matches[:5]
        result["note"] = f"检测到 {len(unique_matches)} 处关键词呼应" if len(unique_matches) >= 2 else "检测到关键词呼应"
    else:
        result["note"] = "上章悬念关键词未在本章开头出现"
        result["suggestion"] = "建议在本章开头1-3段内提及上章末尾的人/事/物，例如：'望着那道突然出现的身影，XX瞳孔骤缩...'"

    return result


def scan_chapter(file_path: Path) -> Optional[Dict]:
    raw_text = read_file(file_path)
    if raw_text is None:
        return None
    clean_text = strip_markdown(raw_text)
    word_count = count_words(clean_text)
    title = extract_title(raw_text, file_path.name)
    author_note = extract_author_note(raw_text)
    cliffhanger_details = extract_cliffhanger_details(raw_text)

    return {
        "file_path": str(file_path),
        "file_name": file_path.name,
        "title": title,
        "word_count": word_count,
        "chinese_chars": count_chinese_chars(clean_text),
        "english_words": count_english_words(clean_text),
        "author_note": author_note,
        "has_author_note": author_note is not None,
        "cliffhanger_cues": [d["sentence"] for d in cliffhanger_details],
        "cliffhanger_details": cliffhanger_details,
        "last_paragraphs": extract_last_paragraphs(raw_text, 3),
        "head_paragraphs": extract_head_paragraphs(raw_text, 3),
        "modified_time": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
        "modified_ts": int(file_path.stat().st_mtime),
        "size_bytes": file_path.stat().st_size,
    }


def scan_draft_dir(draft_dir: str) -> Dict[str, List[Dict]]:
    """扫描草稿目录。

    新版分类逻辑（不再依赖文件名）：
    - 所有文件都作为章节扫描
    - 返回 all / published / drafts 三个列表
    - published 和 drafts 由调用方结合 mark_published 记录判断
    - 这里默认：published=[], drafts=all，分类留给上层
    """
    draft_path = Path(draft_dir)
    if not draft_path.exists() or not draft_path.is_dir():
        return {"all": [], "published": [], "drafts": [], "empty": True}

    chapters = []
    for ext in SUPPORTED_EXTENSIONS:
        for file_path in draft_path.rglob(f"*{ext}"):
            if file_path.is_file():
                chapter = scan_chapter(file_path)
                if chapter:
                    chapters.append(chapter)

    chapters.sort(key=lambda c: c["file_name"])

    return {
        "all": chapters,
        "published": [],
        "drafts": list(chapters),
        "empty": len(chapters) == 0,
    }


def classify_chapters_by_published(all_chapters: List[Dict], check_published_fn) -> Dict[str, List[Dict]]:
    """根据上层的「已发布记录」把章节分成已发布/草稿两类。"""
    published = []
    drafts = []
    for ch in all_chapters:
        if check_published_fn(ch):
            published.append(ch)
        else:
            drafts.append(ch)
    return {
        "all": all_chapters,
        "published": sorted(published, key=lambda c: c["file_name"]),
        "drafts": sorted(drafts, key=lambda c: c["file_name"]),
        "empty": len(all_chapters) == 0,
    }


def get_chapter_word_delta_vs_baseline(chapter: Dict, baseline_words_fn) -> Tuple[int, int]:
    """计算相对基线的增量。"""
    baseline = baseline_words_fn(chapter["title"])
    current = chapter["word_count"]
    delta = current - baseline
    return delta, baseline


def get_chapter_word_delta_vs_snapshot(chapter: Dict, snapshot_getter) -> Tuple[int, int]:
    """计算相对上次快照的增量（保留用于 progress 自动检测今日增量）。"""
    snapshot = snapshot_getter(chapter["title"])
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
