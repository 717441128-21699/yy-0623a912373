import os
import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Dict, List, Any


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


def load_history() -> Dict[str, Any]:
    path = get_history_path()
    if not path.exists():
        return {"daily_records": {}, "chapter_snapshots": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            data.setdefault("daily_records", {})
            data.setdefault("chapter_snapshots", {})
            return data
    except (json.JSONDecodeError, IOError):
        return {"daily_records": {}, "chapter_snapshots": {}}


def save_history(history: Dict[str, Any]) -> None:
    path = get_history_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def record_daily(date_str: str, word_count: int, chapter_name: str = None) -> None:
    history = load_history()
    records = history["daily_records"]
    if date_str not in records:
        records[date_str] = {
            "total_words": 0,
            "sessions": [],
            "chapters": [],
        }
    day_record = records[date_str]
    session = {
        "time": datetime.now().isoformat(),
        "words": word_count,
        "chapter": chapter_name,
    }
    day_record["sessions"].append(session)
    day_record["total_words"] = sum(int(s.get("words", 0)) for s in day_record["sessions"])
    if chapter_name and chapter_name not in day_record["chapters"]:
        day_record["chapters"].append(chapter_name)
    save_history(history)


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
            "total_words": record.get("total_words", 0),
            "chapters": record.get("chapters", []),
        })
    return result


def update_chapter_snapshot(chapter_name: str, word_count: int, file_path: str) -> None:
    history = load_history()
    snapshots = history["chapter_snapshots"]
    snapshots[chapter_name] = {
        "word_count": word_count,
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
