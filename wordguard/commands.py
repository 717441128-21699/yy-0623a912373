import sys
import os
import re
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, List, Tuple


from .config import (
    load_config, save_config, init_config,
    load_history, save_history,
    record_daily, get_daily_record, get_recent_days,
    update_chapter_snapshot, get_all_chapter_snapshots,
)
from .scanner import (
    scan_draft_dir, scan_chapter, count_words, strip_markdown,
    get_chapter_word_delta, classify_chapter_status, extract_title,
)


# ============================================================
# 色彩辅助
# ============================================================
class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"


def use_color() -> bool:
    return sys.stdout.isatty()


def c(text: str, color: str) -> str:
    if not use_color():
        return text
    return f"{color}{text}{Color.RESET}"


def bold(text: str) -> str:
    return c(text, Color.BOLD)


def dim(text: str) -> str:
    return c(text, Color.DIM)


def hr(width: int = 48, char: str = "─") -> str:
    return dim(char * width)


# ============================================================
# Init 命令
# ============================================================
def cmd_init(args) -> int:
    book_name = args.book_name
    daily_target = args.daily_target
    publish_time = args.publish_time
    draft_dir = args.draft_dir
    safe_chapters = args.safe_chapters
    publish_line_ratio = args.publish_line_ratio

    if not book_name:
        book_name = input("作品名称: ").strip()
    if not daily_target:
        dt = input("日更目标字数 (默认 4000): ").strip()
        daily_target = int(dt) if dt else 4000
    else:
        daily_target = int(daily_target)
    if not publish_time:
        pt = input("每日发布时间 HH:MM (默认 20:00): ").strip()
        publish_time = pt if pt else "20:00"
    if not draft_dir:
        dd = input("草稿目录路径: ").strip()
        draft_dir = dd
    if not draft_dir:
        print(c("错误: 草稿目录不能为空", Color.RED))
        return 1
    if not safe_chapters:
        sc = input("安全存稿章节数 (默认 3): ").strip()
        safe_chapters = int(sc) if sc else 3
    else:
        safe_chapters = int(safe_chapters)
    if not publish_line_ratio:
        plr = input("发布线比例 (默认 0.8, 即 80% 日更字数): ").strip()
        publish_line_ratio = float(plr) if plr else 0.8
    else:
        publish_line_ratio = float(publish_line_ratio)

    draft_dir = os.path.abspath(os.path.expanduser(draft_dir))
    if not os.path.exists(draft_dir):
        try:
            os.makedirs(draft_dir, exist_ok=True)
            print(dim(f"  已创建目录: {draft_dir}"))
        except OSError as e:
            print(c(f"错误: 无法创建目录 {draft_dir}: {e}", Color.RED))
            return 1

    config = init_config(book_name, daily_target, publish_time, draft_dir, safe_chapters, publish_line_ratio)

    print()
    print(bold(c("✓ 初始化完成", Color.GREEN)))
    print(hr())
    daily_target_val = config["daily_target"]
    publish_line_val = int(config["daily_target"] * config["publish_line_ratio"])
    safe_chapters_val = config["safe_chapters"]
    print(f"  作品名称:    {c(config['book_name'], Color.CYAN)}")
    print(f"  日更目标:    {c(f'{daily_target_val} 字', Color.YELLOW)}")
    print(f"  发布时间:    {c(config['publish_time'], Color.YELLOW)}")
    print(f"  发布线:      {c(f'{publish_line_val} 字', Color.YELLOW)}")
    print(f"  草稿目录:    {c(config['draft_dir'], Color.BLUE)}")
    print(f"  安全存稿:    {c(f'{safe_chapters_val} 章', Color.YELLOW)}")
    print(hr())
    print(dim("  接下来试试: wg progress   查看当前进度"))
    print(dim("             wg check      检查是否会断更"))
    print(dim("             wg publish    发布前清单核对"))
    return 0


# ============================================================
# Progress 命令
# ============================================================
def _ensure_config() -> Optional[Dict[str, Any]]:
    cfg = load_config()
    if cfg is None:
        print(c("错误: 尚未初始化, 请先运行 wg init", Color.RED))
        return None
    return cfg


def _parse_time(t: str) -> Optional[Tuple[int, int]]:
    try:
        parts = t.split(":")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except (ValueError, AttributeError):
        pass
    return None


def _build_progress_bar(current: int, target: int, width: int = 28) -> str:
    if target <= 0:
        target = 1
    ratio = min(current / target, 1.0)
    filled = int(ratio * width)
    empty = width - filled
    bar = c("█" * filled, Color.GREEN if ratio >= 1 else (Color.YELLOW if ratio >= 0.5 else Color.RED))
    bar += c("░" * empty, Color.GRAY)
    pct = f"{ratio * 100:.0f}%"
    return f"{bar} {pct}"


def _estimate_finish_time(
    current_words: int, target_words: int,
    now: datetime, start_of_day: datetime, start_words: int,
) -> Optional[datetime]:
    remaining = target_words - current_words
    if remaining <= 0:
        return now
    elapsed = (now - start_of_day).total_seconds() / 3600
    written = current_words - start_words
    if elapsed <= 0 or written <= 0:
        return None
    speed = written / elapsed
    if speed <= 0:
        return None
    hours_needed = remaining / speed
    return now + timedelta(hours=hours_needed)


def cmd_progress(args) -> int:
    cfg = _ensure_config()
    if cfg is None:
        return 1

    today = date.today().isoformat()
    now = datetime.now()
    target = cfg["daily_target"]
    publish_line = int(target * cfg["publish_line_ratio"])
    draft_dir = cfg["draft_dir"]

    chapters_data = scan_draft_dir(draft_dir)
    all_chapters = chapters_data["all"]
    draft_chapters = chapters_data["drafts"]

    snapshots = get_all_chapter_snapshots()

    total_today_new = 0
    chapter_deltas = []

    for ch in all_chapters:
        delta, prev = get_chapter_word_delta(ch)
        if delta > 0:
            total_today_new += delta
            chapter_deltas.append((ch, delta, prev))
            record_daily(today, delta, ch["title"])
        update_chapter_snapshot(ch["title"], ch["word_count"], ch["file_path"])

    manual_record = get_daily_record(today)
    manual_words = manual_record.get("total_words", 0) if manual_record else 0
    total_today_new = manual_words

    if args.words:
        add_words = int(args.words)
        chapter_name = args.chapter or None
        if add_words > 0:
            record_daily(today, add_words, chapter_name)
            manual_words += add_words
            total_today_new += add_words
            print(c(f"  +{add_words} 字", Color.GREEN) + dim(f" 已记录" + (f" ({chapter_name})" if chapter_name else "")))
            print()

    total_current = total_today_new
    remaining = max(0, target - total_current)

    # 输出头部
    print()
    print(bold(c(f"《{cfg['book_name']}》", Color.CYAN)) + dim("  ·  ") + c(today, Color.GRAY))
    print(hr())

    # 今日进度
    print(bold("  今日进度"))
    print()
    print(f"    {_build_progress_bar(total_current, target)}")
    print()
    print(f"    今日新增:   {c(f'{total_current} 字', Color.BOLD + (Color.GREEN if total_current >= target else Color.YELLOW))}")
    print(f"    目标字数:   {target} 字")
    print(f"    剩余还差:   {c(f'{remaining} 字', Color.RED if remaining > 0 else Color.GREEN)}")
    print(f"    发布线:     {publish_line} 字 " + (c("✓ 已达", Color.GREEN) if total_current >= publish_line else c("✗ 未达", Color.YELLOW)))
    print()

    # 速度与预计
    print(bold("  速度与预计"))
    print()
    today_start = datetime.combine(date.today(), datetime.min.time())
    est = _estimate_finish_time(total_current, target, now, today_start, 0)
    if est:
        time_str = est.strftime("%H:%M")
        publish_pt = _parse_time(cfg["publish_time"])
        status_color = Color.GREEN
        status_text = "能准时发"
        if publish_pt:
            publish_dt = now.replace(hour=publish_pt[0], minute=publish_pt[1], second=0, microsecond=0)
            if est > publish_dt:
                status_color = Color.RED
                delay = (est - publish_dt).total_seconds() / 60
                status_text = f"将晚 {delay:.0f} 分钟"
        print(f"    预计完成:   {c(time_str, status_color)} {dim(f'({status_text})')}")
    else:
        print(f"    预计完成:   {dim('数据不足, 写一点再算')}")

    elapsed_hours = max((now - today_start).total_seconds() / 3600, 0.01)
    speed = total_current / elapsed_hours if elapsed_hours > 0 else 0
    print(f"    当前速度:   {speed:.0f} 字/小时")
    if remaining > 0 and speed > 0:
        print(f"    剩余时间:   {remaining / speed:.1f} 小时 ({remaining / speed * 60:.0f} 分钟)")
    print()

    # 章节动态
    if chapter_deltas or draft_chapters:
        print(bold("  章节动态"))
        print()
        if chapter_deltas:
            for ch, delta, prev in sorted(chapter_deltas, key=lambda x: -x[1])[:5]:
                wc = ch["word_count"]
                status = classify_chapter_status(ch, publish_line)
                status_c = {"ready": Color.GREEN, "writing": Color.YELLOW, "outline": Color.RED}[status]
                status_t = {"ready": "可发", "writing": "撰写中", "outline": "刚开"}[status]
                print(f"    {c('+%d' % delta, status_c)} {ch['title'][:24]:<24}  {dim(f'{wc} 字')} {c(f'[{status_t}]', status_c)}")
        if draft_chapters:
            for ch in draft_chapters[:3]:
                if not any(cd[0]["title"] == ch["title"] for cd in chapter_deltas):
                    wc = ch["word_count"]
                    status = classify_chapter_status(ch, publish_line)
                    status_c = {"ready": Color.GREEN, "writing": Color.YELLOW, "outline": Color.RED}[status]
                    status_t = {"ready": "可发", "writing": "撰写中", "outline": "刚开"}[status]
                    print(f"    {dim('  0')} {ch['title'][:24]:<24}  {dim(f'{wc} 字')} {c(f'[{status_t}]', status_c)}")
        print()

    # 存稿概况
    total_draft_words = sum(ch["word_count"] for ch in draft_chapters)
    draft_ready = sum(1 for ch in draft_chapters if classify_chapter_status(ch, publish_line) == "ready")
    if all_chapters:
        print(bold("  存稿概况"))
        print()
        print(f"    总章节:     {len(all_chapters)} 章")
        print(f"    存稿章节:   {len(draft_chapters)} 章 " + (c("✓", Color.GREEN) if len(draft_chapters) >= cfg["safe_chapters"] else c("!", Color.YELLOW)))
        print(f"    可发章节:   {draft_ready} 章")
        print(f"    存稿字数:   {total_draft_words} 字 " + dim(f"(约 {max(1, total_draft_words // target)} 天量)"))
        print()

    # 发布时间提醒
    publish_pt = _parse_time(cfg["publish_time"])
    if publish_pt:
        publish_dt = now.replace(hour=publish_pt[0], minute=publish_pt[1], second=0, microsecond=0)
        diff = publish_dt - now
        diff_min = int(diff.total_seconds() / 60)
        if diff_min > 0 and diff_min < 360:
            print(c(f"  ⏰ 距离 {cfg['publish_time']} 发布还有 {diff_min} 分钟", Color.MAGENTA))
        elif diff_min < 0 and total_current < publish_line:
            print(c(f"  ⚠ 已过发布时间 {cfg['publish_time']}, 但还差 {max(0, publish_line - total_current)} 字到发布线", Color.RED))
        print()

    return 0


# ============================================================
# Check 命令
# ============================================================
def _check_decreasing_trend(days: List[Dict]) -> Tuple[bool, int]:
    non_zero = [d for d in days if d["total_words"] > 0]
    if len(non_zero) < 3:
        return False, 0
    streak = 0
    max_streak = 0
    for i in range(1, len(non_zero)):
        if non_zero[i]["total_words"] < non_zero[i - 1]["total_words"]:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak >= 3, max_streak


def cmd_check(args) -> int:
    cfg = _ensure_config()
    if cfg is None:
        return 1

    today = date.today().isoformat()
    now = datetime.now()
    target = cfg["daily_target"]
    publish_line = int(target * cfg["publish_line_ratio"])
    safe_chapters = cfg["safe_chapters"]

    chapters_data = scan_draft_dir(cfg["draft_dir"])
    all_chapters = chapters_data["all"]
    draft_chapters = chapters_data["drafts"]

    for ch in all_chapters:
        delta, _ = get_chapter_word_delta(ch)
        if delta > 0:
            record_daily(today, delta, ch["title"])
        update_chapter_snapshot(ch["title"], ch["word_count"], ch["file_path"])

    today_record = get_daily_record(today)
    total_today_new = today_record.get("total_words", 0) if today_record else 0

    # 近七天
    recent = get_recent_days(7)

    # 存稿达标
    draft_count = len(draft_chapters)
    draft_ready = sum(1 for ch in draft_chapters if classify_chapter_status(ch, publish_line) == "ready")

    # 趋势检查
    decr, decr_days = _check_decreasing_trend(recent)

    warnings = []
    successes = []

    # 1. 发布线
    if total_today_new >= publish_line:
        ratio = total_today_new / publish_line
        successes.append(("今日发布线", f"已达 {total_today_new}/{publish_line} 字 ({ratio*100:.0f}%)", "够发"))
    else:
        remaining = publish_line - total_today_new
        publish_pt = _parse_time(cfg["publish_time"])
        urgent = ""
        if publish_pt:
            publish_dt = now.replace(hour=publish_pt[0], minute=publish_pt[1], second=0, microsecond=0)
            diff_min = int((publish_dt - now).total_seconds() / 60)
            if diff_min < 120:
                urgent = f" [紧急: 只剩 {diff_min} 分钟]"
        warnings.append(("今日发布线", f"还差 {remaining} 字 ({total_today_new}/{publish_line}){urgent}", "未达标"))

    # 2. 存稿安全
    if draft_count >= safe_chapters:
        successes.append(("存稿安全", f"{draft_count} 章草稿 (目标 {safe_chapters}), {draft_ready} 章可发", "充足"))
    else:
        lack = safe_chapters - draft_count
        warnings.append(("存稿安全", f"仅 {draft_count} 章草稿, 缺 {lack} 章 (目标 {safe_chapters})", "偏低"))

    # 3. 七天趋势
    if not decr:
        if decr_days > 0:
            successes.append(("七天趋势", f"连续下滑 {decr_days} 天, 未超警戒线", "平稳"))
        else:
            successes.append(("七天趋势", "字数无连续下滑", "健康"))
    else:
        warnings.append(("七天趋势", f"连续 {decr_days} 天字数下滑, 警惕断更前兆", "警告"))

    # 4. 发布时间
    publish_pt = _parse_time(cfg["publish_time"])
    if publish_pt:
        publish_dt = now.replace(hour=publish_pt[0], minute=publish_pt[1], second=0, microsecond=0)
        diff_min = int((publish_dt - now).total_seconds() / 60)
        if 0 < diff_min < 180 and total_today_new < publish_line:
            warnings.append(("发布时间", f"距离 {cfg['publish_time']} 还有 {diff_min} 分钟, 但还差 {publish_line - total_today_new} 字", "紧迫"))
        elif diff_min < 0 and total_today_new < publish_line:
            warnings.append(("发布时间", f"已过 {cfg['publish_time']} {-diff_min} 分钟, 今日可能断更", "已超时"))

    # 5. 连续断更
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    yd = get_daily_record(yesterday)
    yesterday_words = yd.get("total_words", 0) if yd else 0
    if yesterday_words < publish_line:
        # 看看是不是真的没写（扫描字数也没变化）
        warnings.append(("昨日记录", f"昨日新增 {yesterday_words} 字, 未达发布线", "昨日缺口"))

    # ====== 输出 ======
    print()
    print(bold(c("断更检查报告", Color.MAGENTA)) + dim("  ·  ") + cfg["book_name"])
    print(hr())
    print()

    if successes:
        print(bold(c("  ✓ 正常项", Color.GREEN)))
        print()
        for name, detail, status in successes:
            print(f"    {c('●', Color.GREEN)} {name:<12} {detail} {dim(f'[{status}]')}")
        print()

    if warnings:
        print(bold(c("  ⚠ 警告项", Color.YELLOW if len(warnings) <= 2 else Color.RED)))
        print()
        for name, detail, status in warnings:
            color = Color.YELLOW if len(warnings) <= 2 else Color.RED
            print(f"    {c('▲', color)} {name:<12} {c(detail, color)} {dim(f'[{status}]')}")
        print()

    if not warnings:
        print(c("  ★ 今日一切正常, 安心写稿", Color.GREEN))
    elif len(warnings) >= 3:
        print(c("  ⚠ 警告过多, 建议立刻集中处理", Color.RED))
    print()

    # 七天柱状图
    print(bold("  近 7 天字数"))
    print()
    max_words = max((d["total_words"] for d in recent), default=1) or 1
    bar_max = 20
    for d in recent:
        dstr = d["date"][5:]
        words = d["total_words"]
        bar_len = int(words / max_words * bar_max)
        bar = c("█" * bar_len, Color.CYAN) if words >= publish_line else (c("▓" * bar_len, Color.YELLOW) if words > 0 else dim("·" * bar_len))
        pad = " " * (bar_max - bar_len)
        mark = ""
        if d["date"] == today:
            mark = c(" ◀今天", Color.MAGENTA)
        elif words < publish_line:
            mark = dim(" ✗")
        else:
            mark = dim(" ✓")
        print(f"    {dstr}  {bar}{pad}  {words:>6} 字{mark}")
    print()
    print(f"    发布线基准: {publish_line} 字/天  {dim('█ 达标  ▓ 未达标')}")
    print()

    return len(warnings)


# ============================================================
# Publish 命令
# ============================================================
def _get_next_publish_chapter(draft_chapters: List[Dict], publish_line: int) -> Optional[Dict]:
    ready = [ch for ch in draft_chapters if classify_chapter_status(ch, publish_line) == "ready"]
    if ready:
        return ready[0]
    if draft_chapters:
        return sorted(draft_chapters, key=lambda c: -c["word_count"])[0]
    return None


def _get_previous_chapter(published_chapters: List[Dict]) -> Optional[Dict]:
    if published_chapters:
        return published_chapters[-1]
    return None


def cmd_publish(args) -> int:
    cfg = _ensure_config()
    if cfg is None:
        return 1

    target = cfg["daily_target"]
    publish_line = int(target * cfg["publish_line_ratio"])
    chapters_data = scan_draft_dir(cfg["draft_dir"])
    draft_chapters = chapters_data["drafts"]
    published_chapters = chapters_data["published"]

    if args.chapter:
        # 手动指定章节名/路径
        from pathlib import Path
        from .scanner import scan_chapter as _scan_ch
        p = Path(args.chapter)
        if p.exists():
            ch = _scan_ch(p)
        else:
            ch = next((c for c in draft_chapters + published_chapters if args.chapter in c["title"] or args.chapter in c["file_name"]), None)
        if ch is None:
            print(c(f"错误: 找不到章节 '{args.chapter}'", Color.RED))
            return 1
        next_ch = ch
        # 找它的上一章
        all_sorted = sorted(chapters_data["all"], key=lambda c: c["file_name"])
        idx = next((i for i, c in enumerate(all_sorted) if c["file_path"] == ch["file_path"]), -1)
        prev_ch = all_sorted[idx - 1] if idx > 0 else None
    else:
        next_ch = _get_next_publish_chapter(draft_chapters, publish_line)
        prev_ch = _get_previous_chapter(published_chapters)

    if next_ch is None:
        print(c("错误: 没有找到可发布的章节", Color.RED))
        print(dim("  请检查草稿目录是否有文件, 或用 wg progress 查看当前存稿"))
        return 1

    # ====== 构建清单 ======
    checks = []

    # 1. 章节标题
    has_title = bool(next_ch["title"].strip()) and len(next_ch["title"].strip()) >= 2
    title_text = next_ch["title"][:40] if has_title else "(空)"
    checks.append({
        "name": "章节标题",
        "desc": title_text,
        "ok": has_title,
        "hint": None if has_title else "文件开头没有找到有效标题 (如 # 第X章 ...)",
        "weight": 1,
    })

    # 2. 字数是否够
    wc = next_ch["word_count"]
    enough = wc >= publish_line
    ratio = wc / publish_line * 100
    checks.append({
        "name": "字数达标",
        "desc": f"{wc} / {publish_line} 字 ({ratio:.0f}%)",
        "ok": enough,
        "hint": None if enough else f"距离发布线还差 {publish_line - wc} 字",
        "weight": 2,
    })

    # 3. 悬念衔接
    connected = False
    connection_note = ""
    if prev_ch and prev_ch.get("cliffhanger_cues"):
        prev_cues = prev_ch["cliffhanger_cues"]
        # 从下一章开头找关键词匹配
        next_text = "\n".join(next_ch.get("last_paragraphs", [])[:2])  # 其实是中间，取开头
        try:
            with open(next_ch["file_path"], "r", encoding="utf-8") as f:
                next_begin = f.read(800)
        except:
            next_begin = ""
        # 简单启发：看下一章开头是否提到上一章悬念中的关键
        connected = any(any(word[:2] in next_begin for word in re.findall(r'[\u4e00-\u9fff]{2,}', cue)) for cue in prev_cues)
        if connected:
            connection_note = "检测到关键词呼应"
        elif prev_cues:
            connection_note = f"上章悬念关键词未在下章开头出现"
    else:
        connected = True  # 没有上一章，跳过
        connection_note = "第一章或无上章记录"

    prev_hint = ""
    if prev_ch and prev_ch.get("cliffhanger_cues"):
        prev_hint = f"\n       上章悬念尾段: {dim(prev_ch['cliffhanger_cues'][0][:60])}"

    checks.append({
        "name": "悬念衔接",
        "desc": connection_note + prev_hint,
        "ok": connected,
        "hint": None if connected else "请确认上一章末尾悬念是否在本章开篇得到承接或回应",
        "weight": 2,
    })

    # 4. 作者有话说
    has_note = next_ch.get("has_author_note", False)
    note_preview = ""
    if has_note and next_ch.get("author_note"):
        note_preview = f': "{next_ch["author_note"][:40]}..."'
    checks.append({
        "name": "作者有话说",
        "desc": ("已填写" + note_preview) if has_note else "未填写",
        "ok": has_note,
        "hint": None if has_note else "建议在章节末尾加上 '作者有话说:' 段落, 简单写两句也可以",
        "weight": 0,
    })

    # 5. 本章结尾留悬念（如果字数够）
    has_cliff = bool(next_ch.get("cliffhanger_cues"))
    if wc >= publish_line:
        checks.append({
            "name": "本章钩子",
            "desc": (f"检测到 {len(next_ch['cliffhanger_cues'])} 处悬念措辞") if has_cliff else "未检测到悬念句",
            "ok": has_cliff,
            "hint": None if has_cliff else "建议在本章末尾加入转折或留扣子, 比如 '忽然' '就在这时' 等",
            "weight": 1,
        })

    # ====== 输出 ======
    print()
    print(bold(c("发布前清单", Color.BLUE)) + dim("  ·  ") + cfg["book_name"])
    print(hr())
    print()

    print(bold("  待发章节"))
    print()
    print(f"    标题:   {c(next_ch['title'], Color.CYAN)}")
    print(f"    文件:   {dim(next_ch['file_path'])}")
    print(f"    字数:   {wc} 字" + (c(f" (日更目标 {target})", Color.DIM)))
    status = classify_chapter_status(next_ch, publish_line)
    sc = {"ready": Color.GREEN, "writing": Color.YELLOW, "outline": Color.RED}[status]
    st = {"ready": "可直接发", "writing": "继续补完", "outline": "草稿阶段"}[status]
    print(f"    状态:   {c(st, sc)}")
    print()

    if prev_ch:
        print(f"    上一章: {dim(prev_ch['title'])}")
        if prev_ch.get("cliffhanger_cues"):
            print(f"            {dim('尾段: ' + prev_ch['cliffhanger_cues'][0][:80])}")
    print()

    print(bold("  核对清单"))
    print()

    pass_count = 0
    fail_count = 0
    warn_count = 0

    for i, ck in enumerate(checks, 1):
        if ck["ok"]:
            pass_count += 1
            icon = c("✓", Color.GREEN)
            icon_line = f"    {icon}"
        elif ck["weight"] == 0:
            warn_count += 1
            icon = c("◌", Color.YELLOW)
            icon_line = f"    {icon}"
        else:
            fail_count += 1
            icon = c("✗", Color.RED)
            icon_line = f"    {icon}"

        print(f"{icon_line} {ck['name']:<10}  {ck['desc']}")
        if ck["hint"] and not ck["ok"]:
            print(f"        {dim('→ ' + ck['hint'])}")
        print()

    # 总结
    print(hr())
    if fail_count == 0:
        if warn_count == 0:
            print(c("  ★ 全部通过, 可以放心发布", Color.GREEN))
        else:
            print(c("  ★ 核心项通过, 建议顺便补充建议项", Color.GREEN))
    elif fail_count == 1:
        print(c("  ⚠ 有 1 项未通过, 建议处理后再发布", Color.YELLOW))
    else:
        print(c(f"  ⚠ 有 {fail_count} 项未通过, 先别急着发", Color.RED))
    print()
    print(dim("  确认后可输入 y/回车继续, 或 q 退出: "), end="", flush=True)

    try:
        resp = input().strip().lower()
    except EOFError:
        resp = ""

    if resp in ("", "y", "yes", "是"):
        if fail_count == 0 or (fail_count == 1 and wc >= publish_line):
            today = date.today().isoformat()
            record_daily(today, wc, next_ch["title"])
            print()
            print(c(f"  ✓ 已记录今日发布 {wc} 字 ({next_ch['title']})", Color.GREEN))
            print(c(f"    请手动将文件从草稿区移至已发布区 (如重命名去掉 draft 标记)", Color.DIM))
        else:
            print()
            print(dim("  已取消: 未通过项目过多, 请先处理"))
    else:
        print()
        print(dim("  已取消发布"))
    print()

    return 0
