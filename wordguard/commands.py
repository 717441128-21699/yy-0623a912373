import sys
import os
import re
import csv
import json
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path


from .config import (
    load_config, save_config, init_config,
    load_history, save_history,
    record_daily, get_daily_record, get_recent_days, get_date_range_records,
    update_chapter_snapshot, get_all_chapter_snapshots, get_chapter_snapshot,
    set_baseline, get_baseline, has_baseline, get_baseline_words_for_chapter,
    is_baseline_included, mark_baseline_included,
    mark_published, get_published_chapters, is_published,
)
from .scanner import (
    scan_draft_dir, scan_chapter, count_words, strip_markdown,
    classify_chapter_status, extract_title,
    classify_chapters_by_published,
    get_chapter_word_delta_vs_baseline, get_chapter_word_delta_vs_snapshot,
    check_cliffhanger_connection, read_file, extract_cliffhanger_details,
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


def hr(width: int = 52, char: str = "─") -> str:
    return dim(char * width)


# ============================================================
# 通用辅助
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


def _build_progress_bar(current: int, target: int, width: int = 30) -> str:
    if target <= 0:
        target = 1
    ratio = min(current / target, 1.0)
    filled = int(ratio * width)
    empty = width - filled
    bar_color = Color.GREEN if ratio >= 1 else (Color.YELLOW if ratio >= 0.5 else Color.RED)
    bar = c("█" * filled, bar_color)
    bar += c("░" * empty, Color.GRAY)
    pct = f"{ratio * 100:.0f}%"
    return f"{bar} {pct}"


def _estimate_finish_time(
    current_words: int, target_words: int,
    now: datetime, start_of_day: datetime,
) -> Optional[datetime]:
    remaining = target_words - current_words
    if remaining <= 0:
        return now
    elapsed = max((now - start_of_day).total_seconds() / 3600, 0.01)
    if current_words <= 0:
        return None
    speed = current_words / elapsed
    if speed <= 0:
        return None
    hours_needed = remaining / speed
    return now + timedelta(hours=hours_needed)


def _scan_and_classify(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """扫描草稿目录并按已发布记录分类。"""
    raw = scan_draft_dir(cfg["draft_dir"])
    return classify_chapters_by_published(raw["all"], is_published)


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

    # 交互缺失参数
    try:
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
    except (EOFError, KeyboardInterrupt):
        print()
        print(dim("已取消"))
        return 130
    except ValueError as e:
        print(c(f"错误: 输入格式不正确 - {e}", Color.RED))
        return 1

    draft_dir = os.path.abspath(os.path.expanduser(draft_dir))
    if not os.path.exists(draft_dir):
        try:
            os.makedirs(draft_dir, exist_ok=True)
            print(dim(f"  已创建目录: {draft_dir}"))
        except OSError as e:
            print(c(f"错误: 无法创建目录 {draft_dir}: {e}", Color.RED))
            return 1

    config = init_config(book_name, daily_target, publish_time, draft_dir, safe_chapters, publish_line_ratio)

    # ---- 新增：立即扫描并设置基线 ----
    chapters_data = scan_draft_dir(draft_dir)
    all_chapters = chapters_data["all"]
    baseline_total = 0
    baseline_count = 0
    if all_chapters:
        baseline_total = set_baseline(all_chapters)
        baseline_count = len(all_chapters)
        # 顺便初始化章节快照，避免第一次 progress 把基线又算成"今日新增"
        for ch in all_chapters:
            update_chapter_snapshot(ch["title"], ch["word_count"], ch["file_path"])

    # ---- 输出 ----
    print()
    print(bold(c("✓ 初始化完成", Color.GREEN)))
    print(hr())
    dt_val = config["daily_target"]
    pl_val = int(config["daily_target"] * config["publish_line_ratio"])
    sc_val = config["safe_chapters"]
    print(f"  作品名称:    {c(config['book_name'], Color.CYAN)}")
    print(f"  日更目标:    {c(f'{dt_val} 字', Color.YELLOW)}")
    print(f"  发布时间:    {c(config['publish_time'], Color.YELLOW)}")
    print(f"  发布线:      {c(f'{pl_val} 字', Color.YELLOW)}")
    print(f"  草稿目录:    {c(config['draft_dir'], Color.BLUE)}")
    print(f"  安全存稿:    {c(f'{sc_val} 章', Color.YELLOW)}")
    print(hr())
    if baseline_count > 0:
        avg = baseline_total // baseline_count if baseline_count else 0
        print(f"  {bold('基线快照:')}  {c(f'{baseline_count} 章 / {baseline_total} 字', Color.MAGENTA)} {dim(f'(平均 {avg} 字/章)')}")
        print(dim("    * 基线 = 初始化时已有的字数，默认不计入今日新增"))
        print(dim("    * 要把基线算进今天，使用: wg progress --include-baseline"))
    else:
        print(f"  {dim('基线快照:')}   {dim('草稿目录为空，基线为 0')}")
    print(hr())
    print(dim("  接下来试试: wg progress   查看当前进度"))
    print(dim("             wg check      检查是否会断更"))
    print(dim("             wg publish    发布前清单核对"))
    print(dim("             wg history    查看 30 天写作日历"))
    return 0


# ============================================================
# Progress 命令
# ============================================================
def cmd_progress(args) -> int:
    cfg = _ensure_config()
    if cfg is None:
        return 1

    today = date.today().isoformat()
    now = datetime.now()
    target = cfg["daily_target"]
    publish_line = int(target * cfg["publish_line_ratio"])

    chapters_data = _scan_and_classify(cfg)
    all_chapters = chapters_data["all"]
    draft_chapters = chapters_data["drafts"]
    published_chapters = chapters_data["published"]

    # ---- 基线逻辑 ----
    include_baseline = bool(getattr(args, "include_baseline", False))
    bl = get_baseline()
    has_bl = has_baseline()
    bl_included = is_baseline_included(today)

    if include_baseline and has_bl and not bl_included:
        # 用户明确要求把基线算入今日
        record_daily(today, bl["total_words"], f"[基线{bl['chapter_count']}章]")
        mark_baseline_included(today, True)
        bl_included = True
        print(c(f"  +{bl['total_words']} 字", Color.MAGENTA) + dim(f" [基线计入] ({bl['chapter_count']} 章)"))
        print()

    # ---- 扫描增量：相对快照（今日内新增）----
    chapter_deltas = []
    for ch in all_chapters:
        delta, _prev = get_chapter_word_delta_vs_snapshot(ch, get_chapter_snapshot)
        if delta > 0:
            chapter_deltas.append((ch, delta, _prev))
            record_daily(today, delta, ch["title"])
        update_chapter_snapshot(ch["title"], ch["word_count"], ch["file_path"])

    # ---- 手动记录 ----
    manual_added = 0
    if args.words:
        add_words = int(args.words)
        chapter_name = args.chapter or None
        if add_words > 0:
            record_daily(today, add_words, chapter_name)
            manual_added = add_words
            print(c(f"  +{add_words} 字", Color.GREEN) + dim(f" 已记录" + (f" ({chapter_name})" if chapter_name else "")))
            print()

    # ---- 汇总今日字数 ----
    today_record = get_daily_record(today)
    total_current = int(today_record.get("total_words", 0)) if today_record else 0
    remaining = max(0, target - total_current)

    # ---- 输出头部 ----
    print()
    header = bold(c(f"《{cfg['book_name']}》", Color.CYAN)) + dim("  ·  ") + c(today, Color.GRAY)
    if bl_included:
        header += dim("  ") + c("[基线已计入]", Color.MAGENTA)
    print(header)
    print(hr())

    # ---- 今日进度 ----
    print(bold("  今日进度"))
    print()
    print(f"    {_build_progress_bar(total_current, target)}")
    print()
    wc_color = Color.BOLD + (Color.GREEN if total_current >= target else (Color.YELLOW if total_current >= publish_line else Color.RED))
    print(f"    今日新增:   {c(f'{total_current} 字', wc_color)}")
    if has_bl and not bl_included:
        print(dim(f"    (基线字数: {bl['total_words']} 字, 使用 -b 将其计入今日)"))
    print(f"    目标字数:   {target} 字")
    print(f"    剩余还差:   {c(f'{remaining} 字', Color.RED if remaining > 0 else Color.GREEN)}")
    print(f"    发布线:     {publish_line} 字 " + (c("✓ 已达", Color.GREEN) if total_current >= publish_line else c("✗ 未达", Color.YELLOW)))
    print()

    # ---- 速度与预计 ----
    print(bold("  速度与预计"))
    print()
    today_start = datetime.combine(date.today(), datetime.min.time())
    est = _estimate_finish_time(total_current, target, now, today_start)
    if est:
        time_str = est.strftime("%H:%M")
        publish_pt = _parse_time(cfg["publish_time"])
        status_color = Color.GREEN
        status_text = "能准时发"
        if publish_pt:
            publish_dt = now.replace(hour=publish_pt[0], minute=publish_pt[1], second=0, microsecond=0)
            if total_current >= publish_line:
                status_text = "已过发布线"
            elif est > publish_dt:
                status_color = Color.RED
                delay = (est - publish_dt).total_seconds() / 60
                status_text = f"将晚 {delay:.0f} 分钟"
            elif (publish_dt - now).total_seconds() < 3600 and total_current < publish_line:
                status_color = Color.YELLOW
                status_text = "临近发布时间"
        print(f"    预计完成:   {c(time_str, status_color)} {dim(f'({status_text})')}")
    else:
        print(f"    预计完成:   {dim('数据不足, 写一点再算')}")

    elapsed_hours = max((now - today_start).total_seconds() / 3600, 0.01)
    speed = total_current / elapsed_hours if elapsed_hours > 0 else 0
    print(f"    当前速度:   {speed:.0f} 字/小时")
    if remaining > 0 and speed > 0:
        print(f"    剩余时间:   {remaining / speed:.1f} 小时 ({remaining / speed * 60:.0f} 分钟)")
    print()

    # ---- 章节动态 ----
    if chapter_deltas or draft_chapters or manual_added:
        print(bold("  章节动态"))
        print()
        if chapter_deltas:
            for ch, delta, prev in sorted(chapter_deltas, key=lambda x: -x[1])[:6]:
                wc = ch["word_count"]
                status = classify_chapter_status(ch, publish_line)
                sc_ = {"ready": Color.GREEN, "writing": Color.YELLOW, "outline": Color.RED}[status]
                st = {"ready": "可发", "writing": "撰写中", "outline": "刚开"}[status]
                print(f"    {c('+%d' % delta, sc_)} {ch['title'][:26]:<26}  {dim(f'{wc} 字')} {c(f'[{st}]', sc_)}")
        # 列出存稿中字数最多但无变化的
        if not chapter_deltas:
            top_drafts = sorted(draft_chapters, key=lambda c: -c["word_count"])[:4]
            for ch in top_drafts:
                wc = ch["word_count"]
                # 相对基线的增量
                vs_bl_delta, bl_wc = get_chapter_word_delta_vs_baseline(ch, get_baseline_words_for_chapter)
                status = classify_chapter_status(ch, publish_line)
                sc_ = {"ready": Color.GREEN, "writing": Color.YELLOW, "outline": Color.RED}[status]
                st = {"ready": "可发", "writing": "撰写中", "outline": "刚开"}[status]
                delta_str = c(f"+{vs_bl_delta}", Color.MAGENTA) if vs_bl_delta > 0 else dim(" 0")
                print(f"    {delta_str} {ch['title'][:26]:<26}  {dim(f'{wc} 字')} {c(f'[{st}]', sc_)}")
        print()

    # ---- 存稿概况 ----
    total_draft_words = sum(ch["word_count"] for ch in draft_chapters)
    draft_ready = sum(1 for ch in draft_chapters if classify_chapter_status(ch, publish_line) == "ready")
    if all_chapters:
        print(bold("  存稿概况"))
        print()
        print(f"    总章节:     {len(all_chapters)} 章 " + dim(f"(已发布 {len(published_chapters)}, 存稿 {len(draft_chapters)})"))
        safe_ok = len(draft_chapters) >= cfg["safe_chapters"]
        print(f"    存稿章节:   {len(draft_chapters)} 章 " + (c("✓", Color.GREEN) if safe_ok else c(f"! (缺 {cfg['safe_chapters'] - len(draft_chapters)} 章)", Color.YELLOW)))
        print(f"    可发章节:   {draft_ready} 章 " + (c("✓", Color.GREEN) if draft_ready >= 1 else dim("(0)")))
        days_stock = max(1, total_draft_words // target) if target > 0 else 1
        print(f"    存稿字数:   {total_draft_words} 字 " + dim(f"(约 {days_stock} 天量)"))
        print()

    # ---- 发布时间提醒 ----
    publish_pt = _parse_time(cfg["publish_time"])
    if publish_pt:
        publish_dt = now.replace(hour=publish_pt[0], minute=publish_pt[1], second=0, microsecond=0)
        diff = publish_dt - now
        diff_min = int(diff.total_seconds() / 60)
        if diff_min > 0 and diff_min < 180 and total_current < publish_line:
            print(c(f"  ⏰ 距离 {cfg['publish_time']} 发布还有 {diff_min} 分钟, 还差 {publish_line - total_current} 字到发布线", Color.MAGENTA))
        elif diff_min < 0 and total_current < publish_line:
            print(c(f"  ⚠ 已过发布时间 {cfg['publish_time']} ({-diff_min} 分钟前), 还差 {max(0, publish_line - total_current)} 字", Color.RED))
        elif diff_min > 0 and diff_min < 60 and total_current >= publish_line:
            print(c(f"  ✓ 距发布还有 {diff_min} 分钟, 已到发布线, 可以发文了", Color.GREEN))
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

    chapters_data = _scan_and_classify(cfg)
    all_chapters = chapters_data["all"]
    draft_chapters = chapters_data["drafts"]
    published_chapters = chapters_data["published"]

    # 扫描增量并记录
    for ch in all_chapters:
        delta, _ = get_chapter_word_delta_vs_snapshot(ch, get_chapter_snapshot)
        if delta > 0:
            record_daily(today, delta, ch["title"])
        update_chapter_snapshot(ch["title"], ch["word_count"], ch["file_path"])

    today_record = get_daily_record(today)
    total_today_new = int(today_record.get("total_words", 0)) if today_record else 0

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
            if diff_min < 60 and total_today_new < publish_line * 0.5:
                urgent = f" [极紧急: 只剩 {diff_min} 分钟, 只写了一半不到]"
            elif diff_min < 120:
                urgent = f" [紧急: 只剩 {diff_min} 分钟]"
            elif diff_min < 0:
                urgent = f" [已超时 {-diff_min} 分钟]"
        warnings.append(("今日发布线", f"还差 {remaining} 字 ({total_today_new}/{publish_line}){urgent}", "未达标"))

    # 2. 存稿安全 (基于 drafts 数量，不含已发布)
    if draft_count >= safe_chapters:
        stock_days = draft_count if draft_count > 0 else 0
        successes.append(("存稿安全", f"{draft_count} 章草稿 (目标 {safe_chapters}), {draft_ready} 章可发", f"充足(约{stock_days}天)"))
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
        if 0 < diff_min < 120 and total_today_new < publish_line:
            ratio = (total_today_new / publish_line * 100) if publish_line else 0
            warnings.append(("发布时间", f"距离 {cfg['publish_time']} 还有 {diff_min} 分钟, 仅完成 {ratio:.0f}%", "紧迫"))
        elif diff_min < 0 and total_today_new < publish_line:
            warnings.append(("发布时间", f"已过 {cfg['publish_time']} {-diff_min} 分钟, 今日有断更风险", "已超时"))

    # 5. 连续断更
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    yd = get_daily_record(yesterday)
    yesterday_words = int(yd.get("total_words", 0)) if yd else 0
    dby = (date.today() - timedelta(days=2)).isoformat()
    dbyd = get_daily_record(dby)
    dby_words = int(dbyd.get("total_words", 0)) if dbyd else 0
    if yesterday_words < publish_line and dby_words < publish_line and total_today_new < publish_line:
        warnings.append(("连续天数", f"前天+昨天+今日上午均未达发布线, 可能连续三天断更", "高危"))
    elif yesterday_words < publish_line:
        warnings.append(("昨日记录", f"昨日新增 {yesterday_words} 字, 未达发布线", "昨日缺口"))

    # 6. 空目录
    if len(all_chapters) == 0:
        warnings.append(("草稿目录", "目录为空或没有可读文件", "无内容"))
    elif len(draft_chapters) == 0 and len(published_chapters) > 0:
        warnings.append(("草稿目录", f"所有 {len(published_chapters)} 章均标记已发布, 无新存稿", "无草稿"))

    # ====== 输出 ======
    print()
    title = bold(c("断更检查报告", Color.MAGENTA)) + dim("  ·  ") + cfg["book_name"]
    if len(published_chapters) > 0:
        title += dim(f"  (已发 {len(published_chapters)} 章)")
    print(title)
    print(hr())
    print()

    if successes:
        print(bold(c("  ✓ 正常项", Color.GREEN)))
        print()
        for name, detail, status in successes:
            print(f"    {c('●', Color.GREEN)} {name:<12} {detail} {dim(f'[{status}]')}")
        print()

    if warnings:
        color_title = Color.YELLOW if len(warnings) <= 2 else Color.RED
        print(bold(c(f"  ⚠ 警告项 ({len(warnings)})", color_title)))
        print()
        for name, detail, status in warnings:
            print(f"    {c('▲', color_title)} {name:<12} {c(detail, color_title)} {dim(f'[{status}]')}")
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
    bar_max = 24
    for d in recent:
        dstr = d["date"][5:]
        words = d["total_words"]
        bar_len = int(words / max_words * bar_max)
        if words >= publish_line:
            bar = c("█" * bar_len, Color.CYAN)
        elif words > 0:
            bar = c("▓" * bar_len, Color.YELLOW)
        else:
            bar = dim("·" * max(1, bar_len))
        pad = " " * (bar_max - bar_len)
        mark = ""
        if d["date"] == today:
            mark = c(" ◀今天", Color.MAGENTA)
        elif words < publish_line and words > 0:
            mark = dim(" ✗")
        elif words >= publish_line:
            mark = dim(" ✓")
        else:
            mark = dim(" —")
        print(f"    {dstr}  {bar}{pad}  {words:>6} 字{mark}")
    print()
    print(f"    发布线基准: {publish_line} 字/天  {dim('█ 达标  ▓ 未达标  — 0')}")
    print()

    return len(warnings)


# ============================================================
# Publish 命令
# ============================================================
def _get_next_publish_chapter(draft_chapters: List[Dict], publish_line: int) -> Optional[Dict]:
    if not draft_chapters:
        return None
    # 先找文件名最靠前且 ready 的
    ready = [ch for ch in sorted(draft_chapters, key=lambda c: c["file_name"]) if classify_chapter_status(ch, publish_line) == "ready"]
    if ready:
        return ready[0]
    # 否则按文件名排序取最靠前的（按章节序号顺序发）
    return sorted(draft_chapters, key=lambda c: c["file_name"])[0]


def _get_previous_chapter(all_sorted: List[Dict], target: Dict) -> Optional[Dict]:
    """找到目标章节的上一章（不管是否已发布，按文件名字序）。"""
    idx = next((i for i, c in enumerate(all_sorted) if c["file_path"] == target["file_path"]), -1)
    if idx > 0:
        return all_sorted[idx - 1]
    return None


def cmd_publish(args) -> int:
    cfg = _ensure_config()
    if cfg is None:
        return 1

    target = cfg["daily_target"]
    publish_line = int(target * cfg["publish_line_ratio"])
    chapters_data = _scan_and_classify(cfg)
    draft_chapters = chapters_data["drafts"]
    all_sorted = sorted(chapters_data["all"], key=lambda c: c["file_name"])

    if args.chapter:
        from pathlib import Path as _P
        p = _P(args.chapter)
        ch = None
        if p.exists():
            ch = scan_chapter(p)
        else:
            for cc in all_sorted:
                if args.chapter in cc["title"] or args.chapter in cc["file_name"]:
                    ch = cc
                    break
        if ch is None:
            print(c(f"错误: 找不到章节 '{args.chapter}'", Color.RED))
            print(dim("  可以用 wg progress 先看一下草稿目录里都有哪些章节"))
            return 1
        next_ch = ch
        prev_ch = _get_previous_chapter(all_sorted, ch)
    else:
        next_ch = _get_next_publish_chapter(draft_chapters, publish_line)
        prev_ch = _get_previous_chapter(all_sorted, next_ch) if next_ch else None

    if next_ch is None:
        print(c("错误: 没有可发布的章节", Color.RED))
        if chapters_data.get("empty"):
            print(dim("  草稿目录为空"))
        elif len(draft_chapters) == 0:
            print(dim("  所有章节都已标记发布, 写新的吧"))
        else:
            print(dim("  用 wg progress 看看当前存稿状态"))
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
        "hint": None if has_title else "文件开头没有找到有效标题 (如 '# 第X章 ...')",
        "weight": 1,
        "details": [],
    })

    # 2. 字数是否够
    wc = next_ch["word_count"]
    enough = wc >= publish_line
    ratio = wc / publish_line * 100 if publish_line else 0
    wc_details = []
    if not enough and wc >= publish_line * 0.5:
        wc_details.append(dim(f"  距离发布线还差 {publish_line - wc} 字, 再写 {(publish_line - wc) / 500 * 15:.0f} 分钟左右差不多"))
    checks.append({
        "name": "字数达标",
        "desc": f"{wc} / {publish_line} 字 ({ratio:.0f}%)",
        "ok": enough,
        "hint": None if enough else f"距离发布线还差 {publish_line - wc} 字",
        "weight": 2,
        "details": wc_details,
    })

    # 3. 悬念衔接（详细信息）
    cliff_desc_parts = []
    cliff_ok = True
    cliff_weight = 2
    cliff_hint = None
    cliff_details = []

    if prev_ch:
        conn = check_cliffhanger_connection(prev_ch, next_ch)
        # 展示上一章悬念关键词
        prev_chs = conn.get("prev_cliffhangers", [])
        if prev_chs:
            cliff_details.append(dim("  【上一章悬念】"))
            for ch_info in prev_chs[:2]:
                kw = ", ".join(ch_info.get("keywords", [])[:5])
                cliff_details.append(f"    {c('关键词:', Color.MAGENTA)}{c(kw, Color.CYAN)}")
                cliff_details.append(f"    {dim('原句: ' + ch_info.get('sentence', '')[:80])}")
            # 展示命中的片段
            hits = conn.get("matched_hits", [])
            if hits:
                cliff_details.append(dim("  【本章开头命中】"))
                for h in hits:
                    cliff_details.append(
                        f"    {c('上章:', Color.MAGENTA)}{h['prev_keyword']:<10} "
                        f"{c('→ ', Color.GREEN)}{c(h['next_context'], Color.CYAN)}"
                    )
                cliff_desc_parts.append(conn.get("note", ""))
                cliff_ok = True
            else:
                cliff_desc_parts.append("上章悬念关键词未在本章开头出现")
                cliff_ok = False
                if conn.get("next_head_excerpt"):
                    cliff_details.append(dim("  【本章开头摘要】"))
                    cliff_details.append(dim("    " + conn["next_head_excerpt"][:120]))
                cliff_hint = conn.get("suggestion") or "建议在本章开头 1-3 段内承接上章末尾的悬念"
                cliff_weight = 2
        else:
            cliff_desc_parts.append("上一章未检测到悬念措辞，默认衔接OK")
            cliff_ok = True
    else:
        cliff_desc_parts.append("第一章或无前序章节")
        cliff_ok = True

    checks.append({
        "name": "悬念衔接",
        "desc": " | ".join(p for p in cliff_desc_parts if p),
        "ok": cliff_ok,
        "hint": cliff_hint,
        "weight": cliff_weight,
        "details": cliff_details,
    })

    # 4. 作者有话说
    has_note = next_ch.get("has_author_note", False)
    note_details = []
    note_desc = "未填写"
    if has_note and next_ch.get("author_note"):
        note = next_ch["author_note"]
        note_desc = f"已填写 ({len(note)} 字)"
        note_details.append(dim(f"  预览: \"{note[:60]}{'...' if len(note) > 60 else ''}\""))
    checks.append({
        "name": "作者有话说",
        "desc": note_desc,
        "ok": has_note,
        "hint": None if has_note else "在章节末尾写一行 '作者有话说:' 再写两句就行, 感谢读者也好, 说剧情也好",
        "weight": 0,
        "details": note_details,
    })

    # 5. 本章结尾留钩子
    cliffhook_details = []
    cliffhook_desc = "未检测到悬念句"
    has_cliff = False
    cliffhook_weight = 1
    hook_info = next_ch.get("cliffhanger_details") or []
    if hook_info:
        has_cliff = True
        cliffhook_desc = f"检测到 {len(hook_info)} 处悬念措辞"
        cliffhook_details.append(dim("  【本章末尾悬念】"))
        for h in hook_info[:3]:
            kw = ", ".join(h.get("keywords", [])[:4])
            cliffhook_details.append(f"    {c(kw, Color.MAGENTA)} → {h.get('sentence','')[:70]}")
    elif wc >= publish_line:
        # 字数够了但没钩子，建议加
        cliffhook_details.append(dim("  建议: 在最后 1-2 段加个转折, 比如 '忽然', '就在这时', 留住读者"))
    if wc >= publish_line:
        checks.append({
            "name": "本章钩子",
            "desc": cliffhook_desc,
            "ok": has_cliff,
            "hint": None if has_cliff else "字数够了，建议在末尾加个悬念/转折，留住追更读者",
            "weight": cliffhook_weight,
            "details": cliffhook_details,
        })
    else:
        # 字数不够就不强制钩子检查，但如果有就展示
        if hook_info:
            checks.append({
                "name": "本章钩子",
                "desc": cliffhook_desc,
                "ok": True,
                "hint": None,
                "weight": 0,
                "details": cliffhook_details,
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
    mod_time = next_ch.get("modified_time", "")
    if mod_time:
        try:
            mt = datetime.fromisoformat(mod_time)
            hours_ago = int((datetime.now() - mt).total_seconds() / 3600)
            age_note = f" ({hours_ago} 小时前修改)" if hours_ago > 0 else " (刚修改过)"
            print(f"    修改:   {dim(mod_time[:16] + age_note)}")
        except:
            pass
    print(f"    字数:   {wc} 字" + (c(f" (日更目标 {target})", Color.DIM)))
    status = classify_chapter_status(next_ch, publish_line)
    sc = {"ready": Color.GREEN, "writing": Color.YELLOW, "outline": Color.RED}[status]
    st = {"ready": "可直接发", "writing": "继续补完", "outline": "草稿阶段"}[status]
    print(f"    状态:   {c(st, sc)}")
    print()

    if prev_ch:
        print(f"    上一章: {dim(prev_ch['title'])}")
        prev_wc = prev_ch.get("word_count", 0)
        print(f"            {dim(f'{prev_wc} 字')}")
    else:
        print(f"    上一章: {dim('(无前序章节)')}")
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
        elif ck["weight"] == 0:
            warn_count += 1
            icon = c("◌", Color.YELLOW)
        else:
            fail_count += 1
            icon = c("✗", Color.RED)

        print(f"    {icon} {ck['name']:<10}  {ck['desc']}")
        for d in ck.get("details", []):
            print(f"      {d}")
        if ck["hint"] and not ck["ok"]:
            print(f"        {dim('→ ' + ck['hint'])}")
        print()

    # 总结
    print(hr())
    if fail_count == 0:
        if warn_count == 0:
            print(c("  ★ 全部通过, 可以放心发布", Color.GREEN))
        else:
            print(c("  ★ 核心项通过, 建议顺便补充建议项再发", Color.GREEN))
    elif fail_count == 1:
        print(c("  ⚠ 有 1 项核心项未通过, 建议处理后再发布", Color.YELLOW))
    else:
        print(c(f"  ⚠ 有 {fail_count} 项核心项未通过, 先别急着发", Color.RED))
    print()
    print(dim("  确认后可输入 y/回车 记录并标记已发布, 或 q 退出: "), end="", flush=True)

    try:
        resp = input().strip().lower()
    except EOFError:
        resp = ""

    if resp in ("", "y", "yes", "是"):
        can_record = (fail_count == 0) or (fail_count == 1 and wc >= publish_line)
        if can_record:
            today = date.today().isoformat()
            # 记录发布字数
            record_daily(today, wc, next_ch["title"])
            # 标记已发布（避免下次再算入草稿）
            mark_published(next_ch, today)
            print()
            print(c(f"  ✓ 已记录今日发布 {wc} 字 ({next_ch['title']})", Color.GREEN))
            print(c(f"    已标记该章节为「已发布」, 后续存稿统计不再包含", Color.DIM))
            if len(draft_chapters) - 1 < cfg["safe_chapters"]:
                print(c(f"    ⚠ 发布后存稿只剩 {len(draft_chapters) - 1} 章, 低于安全值 {cfg['safe_chapters']} 章, 该开新稿了", Color.YELLOW))
        else:
            print()
            print(dim(f"  已取消: 未通过项目过多 (fail={fail_count}), 请先处理"))
    else:
        print()
        print(dim("  已取消发布"))
    print()

    return 0


# ============================================================
# History 命令
# ============================================================
def _calc_longest_streak(records: List[Dict], publish_line: int) -> Dict[str, Any]:
    """计算最长连续达标天数、当前连续天数。"""
    longest_streak = 0
    current_streak = 0
    longest_start = None
    longest_end = None
    cur_start = None

    for i, r in enumerate(records):
        ok = r["total_words"] >= publish_line
        if ok:
            if current_streak == 0:
                cur_start = r["date"]
            current_streak += 1
            if current_streak > longest_streak:
                longest_streak = current_streak
                longest_start = cur_start
                longest_end = r["date"]
        else:
            current_streak = 0
            cur_start = None

    # 计算当前连续（只看连续结尾的达标）
    tail_streak = 0
    for r in reversed(records):
        if r["total_words"] >= publish_line:
            tail_streak += 1
        else:
            break

    return {
        "longest_streak": longest_streak,
        "longest_start": longest_start,
        "longest_end": longest_end,
        "current_streak": tail_streak,
    }


def cmd_history(args) -> int:
    cfg = _ensure_config()
    if cfg is None:
        return 1

    days = int(args.days) if args and hasattr(args, "days") and args.days else 30
    export_format = None
    if args and hasattr(args, "export") and args.export:
        ef = str(args.export).lower()
        if ef in ("json", "csv"):
            export_format = ef
        else:
            print(c(f"错误: 不支持的导出格式 '{ef}', 请用 json 或 csv", Color.RED))
            return 1

    today = date.today()
    start_date = today - timedelta(days=days - 1)
    publish_line = int(cfg["daily_target"] * cfg["publish_line_ratio"])
    target = cfg["daily_target"]

    records = get_date_range_records(start_date, today)
    # 去掉记录里包含 baseline 的标记，展示时用
    # records 结构: date, weekday, total_words, chapter_count, session_count, baseline_included

    # ---- 统计 ----
    total_words_all = sum(r["total_words"] for r in records)
    days_reached = sum(1 for r in records if r["total_words"] >= publish_line)
    days_wrote = sum(1 for r in records if r["total_words"] > 0)
    days_zero = days - days_wrote
    reach_rate = (days_reached / days * 100) if days > 0 else 0
    avg_words = (total_words_all / days_wrote) if days_wrote > 0 else 0
    streak = _calc_longest_streak(records, publish_line)

    # ---- 导出逻辑（先算好，不影响展示）----
    if export_format:
        cfg_info = load_config() or {}
        export_data = {
            "book_name": cfg_info.get("book_name", ""),
            "exported_at": datetime.now().isoformat(),
            "date_range": {"from": start_date.isoformat(), "to": today.isoformat()},
            "daily_target": target,
            "publish_line": publish_line,
            "summary": {
                "total_days": days,
                "total_words": total_words_all,
                "days_wrote": days_wrote,
                "days_reached": days_reached,
                "days_zero": days_zero,
                "reach_rate_pct": round(reach_rate, 2),
                "avg_words_on_write_days": round(avg_words, 1),
                "longest_streak": streak["longest_streak"],
                "longest_streak_range": [streak["longest_start"], streak["longest_end"]],
                "current_streak": streak["current_streak"],
            },
            "records": [
                {
                    "date": r["date"],
                    "weekday": r["weekday"],
                    "words": r["total_words"],
                    "reached_publish_line": r["total_words"] >= publish_line,
                    "reached_target": r["total_words"] >= target,
                    "chapter_count": r["chapter_count"],
                    "session_count": r["session_count"],
                    "baseline_included": r["baseline_included"],
                } for r in records
            ],
        }
        out_dir = cfg["draft_dir"]
        base_name = f"wordguard_history_{cfg_info.get('book_name','book')}_{start_date.isoformat()}_{today.isoformat()}".replace(" ", "_")
        if export_format == "json":
            out_path = os.path.join(out_dir, f"{base_name}.json")
            try:
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(export_data, f, ensure_ascii=False, indent=2)
                print(c(f"  ✓ 已导出 JSON: {out_path}", Color.GREEN))
            except Exception as e:
                print(c(f"  ✗ 导出失败: {e}", Color.RED))
                return 1
        else:
            out_path = os.path.join(out_dir, f"{base_name}.csv")
            try:
                with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["日期", "星期", "字数", "过发布线", "过日更目标", "章节数", "写作次数", "含基线"])
                    for r in records:
                        w.writerow([
                            r["date"], r["weekday"], r["total_words"],
                            "是" if r["total_words"] >= publish_line else "否",
                            "是" if r["total_words"] >= target else "否",
                            r["chapter_count"], r["session_count"],
                            "是" if r["baseline_included"] else "否",
                        ])
                print(c(f"  ✓ 已导出 CSV: {out_path}", Color.GREEN))
            except Exception as e:
                print(c(f"  ✗ 导出失败: {e}", Color.RED))
                return 1
        print()
        return 0

    # ---- 终端输出 ----
    print()
    title = bold(c("写作日历", Color.CYAN)) + dim("  ·  ") + cfg["book_name"]
    title += dim(f"  {start_date.isoformat()} ~ {today.isoformat()}")
    print(title)
    print(hr())
    print()

    # 汇总区
    print(bold("  汇总"))
    print()
    cells = [
        (f"总字数", f"{total_words_all} 字", Color.CYAN),
        (f"过发布线", f"{days_reached}/{days} 天", Color.GREEN if reach_rate >= 70 else (Color.YELLOW if reach_rate >= 40 else Color.RED)),
        (f"达标率", f"{reach_rate:.1f}%", Color.GREEN if reach_rate >= 70 else (Color.YELLOW if reach_rate >= 40 else Color.RED)),
        (f"有写天数", f"{days_wrote} 天", Color.CYAN),
        (f"日均(有写)", f"{avg_words:.0f} 字", Color.MAGENTA),
    ]
    for name, val, col in cells:
        print(f"    {name:<10} {c(val, bold(col))}")
    print()
    # 连续更新
    ls_txt = f"{streak['longest_streak']} 天"
    if streak["longest_start"] and streak["longest_end"]:
        ls_txt += dim(f" ({streak['longest_start'][5:]} ~ {streak['longest_end'][5:]})")
    print(f"    {'最长连续':<10} {c(ls_txt, Color.BOLD + Color.MAGENTA)}")
    cur_txt = f"{streak['current_streak']} 天"
    if streak["current_streak"] == 0 and records[-1]["total_words"] < publish_line:
        cur_txt += dim(" (今天还没过线)")
    elif streak["current_streak"] > 0:
        cur_txt += dim(" (继续保持!)")
    print(f"    {'当前连续':<10} {c(cur_txt, Color.BOLD + Color.YELLOW)}")
    print()

    # 日历热力图（按月分组，显示每一周）
    print(bold("  日历热力图"))
    print()
    # 按周展示: 取整到周一开始
    weekday_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
    # 找起始周的周一
    first_day = start_date
    monday_offset = first_day.weekday()
    current = first_day - timedelta(days=monday_offset)

    # 打印头部
    print(dim("         一     二     三     四     五     六     日"))

    record_map = {r["date"]: r for r in records}
    week_idx = 0
    month_label = ""
    while current <= today:
        # 月份标签
        if current.day <= 7 or week_idx == 0:
            month_label = current.strftime("%Y-%m")
        else:
            month_label = "       "

        blocks = []
        for i in range(7):
            d = current + timedelta(days=i)
            dstr = d.isoformat()
            if d < start_date or d > today:
                blocks.append("      ")
                continue
            r = record_map.get(dstr, {"total_words": 0})
            w = r["total_words"]
            # 等级: 0 / 1~50% / 50~100% / >=100%
            if w == 0:
                ch = c("·", Color.GRAY)
            elif w < publish_line * 0.5:
                ch = c("▁", Color.YELLOW)
            elif w < publish_line:
                ch = c("▃", Color.YELLOW)
            elif w < target:
                ch = c("▆", Color.CYAN)
            else:
                ch = c("█", Color.GREEN)
            # 显示日期号
            day_no = f"{d.day:>2}"
            blocks.append(f"{day_no}{ch}  ")
        print(f"    {month_label} " + "".join(blocks))
        current += timedelta(days=7)
        week_idx += 1
    print()
    print(dim("    图例: · 0   ▁ <50%线   ▃ 到发布线前   ▆ 过发布线   █ 过日更"))
    print()

    # 每日详情（只展示有写的 + 最近 7 天）
    print(bold("  每日详情"))
    print()
    # 取最近 14 天 + 所有有写的日子
    recent_cutoff = today - timedelta(days=13)
    shown = [r for r in records if r["total_words"] > 0 or date.fromisoformat(r["date"]) >= recent_cutoff]
    for r in shown:
        d = r["date"]
        w = r["total_words"]
        # 达标标记
        mark = ""
        if w >= target:
            mark = c(" ★", Color.GREEN)
        elif w >= publish_line:
            mark = c(" ✓", Color.CYAN)
        elif w > 0:
            mark = c(" ✗", Color.YELLOW)
        else:
            mark = dim(" —")
        wc_c = Color.GREEN if w >= publish_line else (Color.YELLOW if w > 0 else Color.GRAY)
        baseline_tag = c(" [基]", Color.MAGENTA) if r.get("baseline_included") else ""
        extra = dim(f"  ({r['session_count']}次·{r['chapter_count']}章)") if r["session_count"] > 0 else ""
        bar = ""
        if w > 0:
            bl = max(1, int(w / max(target, 1) * 14))
            bc = Color.GREEN if w >= target else (Color.CYAN if w >= publish_line else Color.YELLOW)
            bar = " " + c("█" * bl, bc)
        print(f"    {d} {r['weekday']:<4} {c(f'{w:>6} 字', wc_c)}{bar}{mark}{baseline_tag}{extra}")
    print()
    print(dim(f"  共 {days} 天, {days_wrote} 天有写, {days_zero} 天空白, 最长连续 {streak['longest_streak']} 天"))
    print(dim(f"  导出: wg history --export json  或  wg history --export csv"))
    print()

    return 0
