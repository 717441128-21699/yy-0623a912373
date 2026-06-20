import sys
import argparse
from typing import List, Optional

from . import __version__
from .commands import (
    cmd_init, cmd_progress, cmd_check, cmd_publish, cmd_history,
    c, Color, bold, dim, hr,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wordguard",
        description="极简命令行码字断更助手 - 帮你追踪日更、检查存稿、发布前核对",
        epilog="示例:\n"
               "  wg init                        # 交互式初始化\n"
               "  wg progress                    # 查看今日进度\n"
               "  wg progress -b                 # 将初始化基线算入今日\n"
               "  wg progress 1500 -c 第42章     # 手动记 1500 字\n"
               "  wg check                       # 断更检查\n"
               "  wg publish                     # 发布前清单核对\n"
               "  wg history --days 30           # 30 天写作日历\n"
               "  wg history --export json       # 导出 JSON 备份\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", "-V", action="version", version=f"wordguard {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # init
    p_init = sub.add_parser("init", help="初始化作品配置 (作品名/日更字数/发布时间/草稿目录)")
    p_init.add_argument("--book-name", "-n", help="作品名称")
    p_init.add_argument("--daily-target", "-t", help="日更目标字数")
    p_init.add_argument("--publish-time", "-p", help="每日发布时间 HH:MM")
    p_init.add_argument("--draft-dir", "-d", help="草稿目录路径")
    p_init.add_argument("--safe-chapters", "-s", help="安全存稿章节数 (默认 3)")
    p_init.add_argument("--publish-line-ratio", "-r", help="发布线比例 (默认 0.8)")

    # progress
    p_prog = sub.add_parser("progress", aliases=["p", "prog"], help="查看/记录今日进度")
    p_prog.add_argument("words", nargs="?", help="手动记录的字数 (如 1500)")
    p_prog.add_argument("--chapter", "-c", help="手动记录时关联的章节名")
    p_prog.add_argument(
        "--include-baseline", "-b", action="store_true",
        help="把初始化时的基线字数也算入今日 (只生效一次, 后续自动跳过)"
    )

    # check
    sub.add_parser("check", aliases=["c"], help="断更检查 (发布线/存稿/趋势/空目录等)")

    # publish
    p_pub = sub.add_parser("publish", aliases=["pub"], help="发布前清单核对 (标题/字数/悬念衔接/作者有话说/本章钩子)")
    p_pub.add_argument("chapter", nargs="?", help="指定章节文件路径或名称 (默认自动选最靠前的草稿)")

    # history
    p_hist = sub.add_parser("history", aliases=["hist", "h"], help="查看写作日历、达标率、连续更新天数")
    p_hist.add_argument("--days", "-d", type=int, default=30, help="查看天数 (默认 30)")
    p_hist.add_argument(
        "--export", "-e", choices=["json", "csv"], default=None,
        help="导出为 JSON 或 CSV 备份到草稿目录"
    )

    return parser


def print_help_summary(parser: argparse.ArgumentParser) -> None:
    print()
    print(bold(c("WordGuard", Color.CYAN)) + dim(" · 码字断更助手 ") + c(f"v{__version__}", Color.GRAY))
    print(hr())
    print()
    print(bold("  常用命令"))
    print()
    print(f"    {c('init', Color.YELLOW):<12} 初始化配置, 记录基线字数快照")
    print(f"    {c('progress', Color.YELLOW):<12} 查看今日进度 (-b 计入基线, 可跟字数手动记录)")
    print(f"    {c('check', Color.YELLOW):<12} 断更风险检查 (发布线/存稿/趋势/空目录)")
    print(f"    {c('publish', Color.YELLOW):<12} 发布前清单核对 (悬念衔接/作者有话说等)")
    print(f"    {c('history', Color.YELLOW):<12} N天写作日历, 达标率, 连续更新 (可导出 JSON/CSV)")
    print()
    print(bold("  快速示例"))
    print()
    print(dim("    wg init                       按提示一步步输入"))
    print(dim("    wg progress                   看看今天真正写了多少 (不含基线)"))
    print(dim("    wg progress -b                想把旧稿也算进今天, 用这个 (只算一次)"))
    print(dim("    wg progress 2000 -c 第42章    手动记 2000 字"))
    print(dim("    wg check                      检查会不会断更"))
    print(dim("    wg publish                    发前走一下清单, 确认后自动标为已发布"))
    print(dim("    wg history -d 30              30 天写作日历"))
    print(dim("    wg history -e json            导出 JSON 备份到草稿目录"))
    print()
    print(dim("  详细帮助: wg --help  或  wg <command> --help"))
    print()


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        print_help_summary(parser)
        return 0

    dispatch = {
        "init": cmd_init,
        "progress": cmd_progress,
        "prog": cmd_progress,
        "p": cmd_progress,
        "check": cmd_check,
        "c": cmd_check,
        "publish": cmd_publish,
        "pub": cmd_publish,
        "history": cmd_history,
        "hist": cmd_history,
        "h": cmd_history,
    }

    func = dispatch.get(args.command)
    if func is None:
        parser.print_help()
        return 1

    try:
        return func(args) or 0
    except KeyboardInterrupt:
        print()
        print(dim("  已取消"))
        return 130
    except Exception as e:
        import traceback
        print(c(f"\n  错误: {e}", Color.RED))
        if "--debug" in sys.argv:
            traceback.print_exc()
        print(dim("  如持续出现, 可用 wg --debug <命令> 查看详情 或 检查草稿目录路径"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
