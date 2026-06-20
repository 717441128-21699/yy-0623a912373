import os
import json
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple


CONFIG_DIR_NAME = ".wordguard"
CONFIG_FILE_NAME = "config.json"
HISTORY_FILE_NAME = "history.json"


def get_config_dir() -> Path:
    home = Path.home()
    config_dir = home / CONFIG_DIR_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_path() -> Path:
    return get_config_dir() / CONFIG_FILE_NAME


def get_history_path() -> Path:
    return get_config_dir() / HISTORY_FILE_NAME


# ============================================================
# Config (作品配置)
# ============================================================
def load_config() -> Optional[Dict[str, Any]]:
    path = get_config_path()
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def save_config(config: Dict[str, Any]) -> None:
    path = get_config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def init_config(
    book_name: str,
    daily_target: int,
    publish_time: str,
    draft_dir: str,
    safe_chapters: int = 3,
    publish_line_ratio: float = 0.8,
) -> Dict[str, Any]:
    config = {
        "book_name": book_name,
        "daily_target": int(daily_target),
        "publish_time": publish_time,
        "draft_dir": os.path.abspath(draft_dir),
        "safe_chapters": int(safe_chapters),
        "publish_line_ratio": float(publish_line_ratio),
        "created_at": datetime.now().isoformat(),
    }
    save_config(config)
    return config


# ============================================================
# History (历史记录: 每日记录/章节快照/基线/已发布章节)
# ============================================================
def load_history() -> Dict[str, Any]:
    path = get_history_path()
    if not path.exists():
        return {
            "daily_records": {},
            "chapter_snapshots": {},
            "baseline_snapshots": {},
            "published_chapters": [],
            "meta": {},
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            data.setdefault("daily_records", {})
            data.setdefault("chapter_snapshots", {})
            data.setdefault("baseline_snapshots", {})
            data.setdefault("published_chapters", [])
            data.setdefault("meta", {})
            return data
    except (json.JSONDecodeError, IOError):
        return {
            "daily_records": {},
            "chapter_snapshots": {},
            "baseline_snapshots": {},
            "published_chapters": [],
            "meta": {},
        }


def save_history(history: Dict[str, Any]) -> None:
    path = get_history_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ============================================================
# 每日记录
# ============================================================
def record_daily(date_str: str, word_count: int, chapter_name: str = None) -> None:
    history = load_history()
    records = history["daily_records"]
    if date_str not in records:
        records[date_str] = {
            "total_words": 0,
            "sessions": [],
            "chapters": [],
            "baseline_included": False,
        }
    day_record = records[date_str]
    session = {
        "time": datetime.now().isoformat(),
        "words": int(word_count),
        "chapter": chapter_name,
    }
    day_record["sessions"].append(session)
    day_record["total_words"] = sum(int(s.get("words", 0)) for s in day_record["sessions"])
    if chapter_name and chapter_name not in day_record["chapters"]:
        day_record["chapters"].append(chapter_name)
    save_history(history)


def mark_baseline_included(date_str: str, included: bool = True) -> None:
    history = load_history()
    records = history["daily_records"]
    if date_str in records:
        records[date_str]["baseline_included"] = included
        save_history(history)


def is_baseline_included(date_str: str) -> bool:
    history = load_history()
    record = history["daily_records"].get(date_str)
    return bool(record and record.get("baseline_included", False))


def get_daily_record(date_str: str) -> Optional[Dict[str, Any]]:
    history = load_history()
    return history["daily_records"].get(date_str)


def get_recent_days(days: int = 7) -> List[Dict[str, Any]]:
    history = load_history()
    records = history["daily_records"]
    result = []
    today = date.today()
    for i in range(days - 1, -1, -1):
        d = today.fromordinal(today.toordinal() - i)
        date_str = d.isoformat()
        record = records.get(date_str, {"total_words": 0, "sessions": [], "chapters": []})
        result.append({
            "date": date_str,
            "total_words": int(record.get("total_words", 0)),
            "chapters": record.get("chapters", []),
            "baseline_included": bool(record.get("baseline_included", False)),
        })
    return result


def get_date_range_records(start_date: date, end_date: date) -> List[Dict[str, Any]]:
    history = load_history()
    records = history["daily_records"]
    result = []
    d = start_date
    while d <= end_date:
        date_str = d.isoformat()
        record = records.get(date_str, {"total_words": 0, "sessions": [], "chapters": []})
        result.append({
            "date": date_str,
            "weekday": d.strftime("%a"),
            "total_words": int(record.get("total_words", 0)),
            "chapter_count": len(record.get("chapters", [])),
            "session_count": len(record.get("sessions", [])),
            "baseline_included": bool(record.get("baseline_included", False)),
        })
        d += timedelta(days=1)
    return result


# ============================================================
# 章节快照 (上次扫描时的字数, 用于计算增量)
# ============================================================
def update_chapter_snapshot(chapter_name: str, word_count: int, file_path: str) -> None:
    history = load_history()
    snapshots = history["chapter_snapshots"]
    snapshots[chapter_name] = {
        "word_count": int(word_count),
        "file_path": file_path,
        "last_updated": datetime.now().isoformat(),
    }
    save_history(history)


def get_chapter_snapshot(chapter_name: str) -> Optional[Dict[str, Any]]:
    history = load_history()
    return history["chapter_snapshots"].get(chapter_name)


def get_all_chapter_snapshots() -> Dict[str, Any]:
    history = load_history()
    return history.get("chapter_snapshots", {})


# ============================================================
# 基线快照 (init 那一刻的所有章节字数)
# ============================================================
def set_baseline(chapters: List[Dict[str, Any]]) -> int:
    history = load_history()
    baseline = {}
    total = 0
    for ch in chapters:
        wc = int(ch.get("word_count", 0))
        baseline[ch["title"]] = {
            "word_count": wc,
            "file_path": ch.get("file_path", ""),
            "file_name": ch.get("file_name", ""),
        }
        total += wc
    history["baseline_snapshots"] = baseline
    history["meta"]["baseline_created_at"] = datetime.now().isoformat()
    history["meta"]["baseline_total_words"] = total
    history["meta"]["baseline_chapter_count"] = len(chapters)
    save_history(history)
    return total


def get_baseline() -> Dict[str, Any]:
    history = load_history()
    return {
        "chapters": history.get("baseline_snapshots", {}),
        "total_words": int(history.get("meta", {}).get("baseline_total_words", 0)),
        "chapter_count": int(history.get("meta", {}).get("baseline_chapter_count", 0)),
        "created_at": history.get("meta", {}).get("baseline_created_at"),
    }


def has_baseline() -> bool:
    return get_baseline()["chapter_count"] > 0


def get_baseline_words_for_chapter(chapter_title: str) -> int:
    bl = get_baseline()
    ch = bl["chapters"].get(chapter_title)
    return int(ch["word_count"]) if ch else 0


# ============================================================
# 已发布章节记录 (publish 命令确认后追加)
# ============================================================
def _chapter_match(p: Dict[str, Any], chapter: Dict[str, Any]) -> bool:
    """严格匹配: 都有路径就只比路径, 都没路径才比标题兜底, 混合情况不匹配(避免重名误判)"""
    pfp = p.get("file_path")
    fp = chapter.get("file_path")
    if pfp and fp:
        return pfp == fp
    if not pfp and not fp:
        pt = p.get("title")
        title = chapter.get("title")
        return bool(pt and title and pt == title)
    return False


def mark_published(chapter: Dict[str, Any], publish_date: str = None) -> None:
    history = load_history()
    published = history["published_chapters"]
    date_str = publish_date or date.today().isoformat()

    existing = next((p for p in published if _chapter_match(p, chapter)), None)
    if existing:
        existing["last_published_at"] = datetime.now().isoformat()
        existing["word_count"] = int(chapter.get("word_count", 0))
    else:
        published.append({
            "title": chapter.get("title"),
            "file_name": chapter.get("file_name"),
            "file_path": chapter.get("file_path"),
            "word_count": int(chapter.get("word_count", 0)),
            "first_published_at": datetime.now().isoformat(),
            "last_published_at": datetime.now().isoformat(),
            "publish_date": date_str,
        })
    save_history(history)


def get_published_chapters() -> List[Dict[str, Any]]:
    history = load_history()
    return history.get("published_chapters", [])


def is_published(chapter: Dict[str, Any]) -> bool:
    published = get_published_chapters()
    return any(_chapter_match(p, chapter) for p in published)
