#!/usr/bin/env python3
"""B站装扮抢购工具 - 主入口"""

import argparse
import os
import sys
import time
from datetime import datetime

import asyncio
import httpx

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
from rich import box

from config import load_config, save_config, AppConfig, GrabConfig, get_cookies_path
from api import BiliAPI, BiliApiError
from login import LoginManager
from graber import GrabEngine
from url_parser import parse_activity_url

console = Console()

BANNER = r"""
╔══════════════════════════════════════════╗
║     🎨 B站装扮抢购工具 v1.0             ║
║     哔哩哔哩 - (゜-゜)つロ 干杯~        ║
╚══════════════════════════════════════════╝
"""

def cmd_dlc(args, api, config):
    """数字卡片抢购"""
    # 如果提供了 --url 参数，自动解析填入 act_id/lottery_id
    if args.url:
        info = parse_activity_url(args.url, api=api)
        if info.parsed:
            console.print(Panel(
                f"[bold cyan]🔗 从链接解析结果[/bold cyan]\n\n"
                f"类型: [yellow]{'数字卡片(DLC)' if info.kind == 'dlc' else info.kind}[/yellow]\n"
                f"活动ID: [cyan]{info.act_id}[/cyan]\n"
                f"抽奖ID: [cyan]{info.lottery_id}[/cyan]\n"
                f"名称: {info.name or '未获取到'}\n"
                f"开售时间: {info.sale_time or '未获取到（请手动指定 -t）'}",
                title="URL 解析",
            ))
            if info.act_id and not args.act_id:
                args.act_id = info.act_id
            if info.lottery_id and args.lottery_id == 113354:
                args.lottery_id = info.lottery_id
            if info.sale_time and not args.time:
                args.time = info.sale_time
        else:
            console.print(f"[red]✗ URL 解析失败: {info.error}[/red]")
            if not Confirm.ask("[yellow]是否继续使用默认参数？[/yellow]"):
                return

    act_id = args.act_id or 113353
    lottery_id = args.lottery_id or 113354
    sale_time = args.time or config.grab.sale_time
    concurrent = args.concurrent or config.grab.concurrent_workers or 8
    max_retries = args.retries or config.grab.max_retries or 30
    advance = args.advance or config.grab.advance_seconds or 0.5

    if not sale_time:
        sale_time = Prompt.ask("[yellow]请输入开售时间 (格式: 2025-01-01 20:00:00)[/yellow]")

    # 确认
    console.print(Panel(
        f"[bold]数字卡片抢购配置[/bold]\n\n"
        f"活动ID: [cyan]{act_id}[/cyan]\n"
        f"抽奖ID: [cyan]{lottery_id}[/cyan]\n"
        f"开售时间: [yellow]{sale_time}[/yellow]\n"
        f"并发数: {concurrent}\n"
        f"提前秒数: {advance}秒\n"
        f"最大重试: {max_retries}",
        title="🎯 数字卡片抢购",
    ))

    if not args.force:
        if not Confirm.ask("[yellow]确认启动抢购？[/yellow]"):
            console.print("[yellow]已取消[/yellow]")
            return

    # 先登录验证
    try:
        nav = api.check_login()
        if not nav.get("isLogin"):
            console.print("[red]✗ 未登录！请先执行 login 命令[/red]")
            return
        console.print(f"[green]✓ 用户: {nav.get('uname')}[/green]")
    except Exception as e:
        console.print(f"[red]✗ 登录检查失败: {e}[/red]")
        return

    # 创建输出回调
    def on_status(msg):
        console.print(msg)

    # 解析目标时间
    try:
        target = datetime.strptime(sale_time, "%Y-%m-%d %H:%M:%S")
        target_ts = target.timestamp()
    except ValueError:
        console.print("[red]✗ 时间格式错误，请使用 YYYY-MM-DD HH:MM:SS 格式[/red]")
        return

    now_ts = time.time()
    if target_ts <= now_ts:
        on_status("[yellow]时间已到或已过，立即开始抢购[/yellow]")
    else:
        on_status(f"[cyan]等待开售: {sale_time} (还剩 {(target_ts-now_ts)/3600:.1f}小时)[/cyan]")

    # 等待到开售时间
    fire_ts = target_ts - advance
    wait_sec = fire_ts - time.time() - 1.0
    if wait_sec > 0:
        on_status(f"[dim]等待 {wait_sec:.0f} 秒后进入忙等待...[/dim]")
        time.sleep(wait_sec)
    while time.time() < fire_ts:
        pass

    # 开始抢购
    on_status(f"[bold green]🔥 开售！发起抢购 (并发{concurrent})[/bold green]")
    start_time = time.time()
    success = False
    order_id = ""

    # 尝试使用的API端点
    api_endpoints = [
        {"path": "/x/garb/trade/create", "data_key": "item_id", "id": lottery_id},
        {"path": "/x/garb/trade/create", "data_key": "item_id", "id": act_id},
    ]

    for attempt in range(1, max_retries + 1):
        if success:
            break

        try:
            csrf = api.get_csrf_token()

            async def single_request(idx, endpoint):
                path = endpoint["path"]
                id_key = endpoint["data_key"]
                id_val = endpoint["id"]
                payload = {id_key: id_val, "num": 1, "csrf": csrf}
                ref = f"https://www.bilibili.com/blackboard/activity-Mz9T5bO5Q3.html?type=dlc&id={act_id}&lottery_id={lottery_id}"

                headers = {
                    "User-Agent": config.bilibili.user_agent,
                    "Referer": ref,
                    "Origin": "https://www.bilibili.com",
                    "Content-Type": "application/x-www-form-urlencoded",
                }
                url = f"{config.bilibili.base_url}{path}"
                async with httpx.AsyncClient(headers=headers, timeout=10, follow_redirects=True) as cl:
                    import json as _json
                    with open(get_cookies_path(), encoding='utf-8') as _f:
                        _ck = _json.load(_f)
                    for _k, _v in _ck.items():
                        if _v:
                            cl.cookies.set(_k, _v, domain='.bilibili.com')
                    try:
                        resp = await cl.post(url, data=payload)
                        data = resp.json()
                        if data.get("code") == 0:
                            return data.get("data", {})
                    except:
                        pass
                return None

            tasks = [single_request(i, ep) for i in range(concurrent) for ep in api_endpoints[:1]]
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            results = loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            loop.close()

            for r in results:
                if isinstance(r, dict) and r:
                    order_id = r.get("order_id", r.get("trade_id", ""))
                    success = True
                    elapsed = time.time() - start_time
                    on_status(f"[✓] 第{attempt}次尝试成功！订单号: {order_id}")
                    on_status(f"    耗时: {elapsed:.2f}秒")
                    console.print(Panel(
                        f"[bold green]🎉 抢购成功！[/bold green]\n\n"
                        f"订单号: [cyan]{order_id}[/cyan]\n"
                        f"尝试次数: {attempt}\n"
                        f"耗时: [green]{elapsed:.2f}秒[/green]",
                        title="✅ 成功",
                        border_style="green",
                    ))
                    return

            on_status(f"[~] 第{attempt}次尝试未成功，重试中...")
            time.sleep(config.grab.retry_interval or 0.5)
        except Exception as e:
            on_status(f"[~] 第{attempt}次出错: {e}")
            time.sleep(config.grab.retry_interval or 0.5)

    elapsed = time.time() - start_time
    console.print(Panel(
        f"[bold red]😢 抢购失败[/bold red]\n\n"
        f"已尝试 {max_retries} 次\n"
        f"耗时: {elapsed:.2f}秒",
        title="❌ 失败",
        border_style="red",
    ))


def cmd_login(args, api, config):
    """登录管理"""
    login_mgr = LoginManager(api, config)

    if args.method == "cookie":
        cookie = args.value or Prompt.ask(
            "[yellow]请输入Cookie字符串[/yellow]",
            password=False,
        )
        if cookie:
            if login_mgr.login_by_cookie(cookie):
                console.print("[green]✓ Cookie设置成功并验证通过[/green]")
            else:
                console.print("[red]✗ Cookie验证失败，请检查是否包含 SESSDATA/bili_jct/DedeUserID[/red]")
        else:
            console.print("[red]✗ 未输入Cookie[/red]")

    elif args.method == "qrcode":
        console.print("[yellow]正在启动扫码登录...[/yellow]")
        login_mgr.login_by_qrcode()

    elif args.method == "browser":
        console.print("[yellow]正在从浏览器提取B站Cookie...[/yellow]")
        if login_mgr.login_by_browser():
            console.print("[green]✓ 从浏览器提取Cookie并登录成功[/green]")
        else:
            console.print("[red]✗ 提取失败，请手动使用 'login cookie' 方式登录[/red]")

    elif args.method == "quick":
        console.print("[cyan]🔑 一键登录：优先浏览器提取 → 失败则扫码[/cyan]")
        success, method = login_mgr.login_quick()
        if success:
            console.print(f"[green]✓ 登录成功！（方式: {method}）[/green]")
        else:
            console.print("[red]✗ 登录失败，请重试或使用其他方式[/red]")

    elif args.method == "status":
        user = login_mgr.get_current_user()
        if user:
            console.print(f"[green]✓ 当前已登录: {user}[/green]")
        else:
            console.print("[red]✗ 未登录或Cookie已过期[/red]")


def cmd_info(args, api, config):
    """查询装扮信息"""
    if args.item_id:
        item_id = int(args.item_id)
    else:
        item_id_str = Prompt.ask("[yellow]请输入装扮商品ID[/yellow]")
        try:
            item_id = int(item_id_str)
        except ValueError:
            console.print("[red]✗ 商品ID必须是数字[/red]")
            return

    console.print(f"[cyan]正在查询装扮信息 (ID: {item_id})...[/cyan]")

    try:
        detail = api.get_suit_detail(item_id)
        table = Table(title=f"🎨 装扮详情 (ID: {item_id})", box=box.ROUNDED)
        table.add_column("字段", style="cyan")
        table.add_column("值", style="white")

        for key in ["id", "name", "price", "sale_time", "sale_status",
                     "stock", "description", "cover"]:
            if key in detail:
                value = detail[key]
                # 美化显示
                if key == "id":
                    value = str(value)
                elif key == "price":
                    value = f"¥{float(value)/100:.2f}" if value else "未知"
                elif key == "sale_time":
                    value = str(value)
                elif key == "cover":
                    value = value[:50] + "..." if len(str(value)) > 50 else value
                table.add_row(key, str(value))

        # 额外字段
        for key in ["item_id", "suit_id", "suit_name", "original_price",
                     "current_price", "stock_num", "sale_begin", "sale_end"]:
            if key in detail:
                table.add_row(key, str(detail[key]))

        console.print(table)

    except BiliApiError as e:
        console.print(f"[red]✗ 查询失败: {e}[/red]")


def cmd_search(args, api, config):
    """搜索装扮"""
    keyword = args.keyword or Prompt.ask("[yellow]请输入搜索关键词[/yellow]")

    console.print(f"[cyan]正在搜索: '{keyword}'...[/cyan]")

    try:
        data = api.search_suit(keyword)
        suits = data if isinstance(data, list) else data.get("list", [])

        if not suits:
            console.print("[yellow]未找到匹配的装扮[/yellow]")
            return

        table = Table(title=f"🔍 搜索结果: '{keyword}'", box=box.ROUNDED)
        table.add_column("ID", style="cyan")
        table.add_column("名称", style="white")
        table.add_column("价格", style="green")
        table.add_column("状态", style="yellow")

        for suit in suits:
            sid = suit.get("id", suit.get("item_id", "?"))
            name = suit.get("name", suit.get("suit_name", "未知"))
            price = suit.get("price", suit.get("current_price", 0))
            if isinstance(price, (int, float)):
                price_str = f"¥{float(price)/100:.2f}"
            else:
                price_str = str(price)
            status = suit.get("sale_status", "")
            status_str = "在售" if status == 1 else "已下架" if status == 0 else str(status)

            table.add_row(str(sid), name, price_str, status_str)

        console.print(table)

    except BiliApiError as e:
        console.print(f"[red]✗ 搜索失败: {e}[/red]")


def cmd_list(args, api, config):
    """查看在售装扮列表"""
    page = args.page or 1

    console.print(f"[cyan]正在获取在售装扮列表 (第{page}页)...[/cyan]")

    try:
        data = api.get_suit_list(page=page)
        suits = data if isinstance(data, list) else data.get("list", [])

        if not suits:
            console.print("[yellow]暂无在售装扮[/yellow]")
            return

        table = Table(title=f"🎨 在售装扮列表 (第{page}页)", box=box.ROUNDED)
        table.add_column("ID", style="cyan")
        table.add_column("名称", style="white")
        table.add_column("价格", style="green")
        table.add_column("库存", style="yellow")

        for suit in suits:
            sid = suit.get("id", suit.get("item_id", "?"))
            name = suit.get("name", suit.get("suit_name", "未知"))
            price = suit.get("price", suit.get("current_price", 0))
            stock = suit.get("stock", suit.get("stock_num", "?"))

            if isinstance(price, (int, float)):
                price_str = f"¥{float(price)/100:.2f}"
            else:
                price_str = str(price)

            table.add_row(str(sid), name, price_str, str(stock))

        console.print(table)

        # 显示页码信息
        total = data.get("total", 0) if isinstance(data, dict) else len(suits)
        console.print(f"[dim]共 {total} 条结果[/dim]")

    except BiliApiError as e:
        console.print(f"[red]✗ 获取列表失败: {e}[/red]")


def get_stock_status(api, item_id: int) -> str:
    """获取库存状态文本"""
    try:
        stock_data = api.get_suit_stock([item_id])
        if isinstance(stock_data, dict):
            stock = stock_data.get(str(item_id), 0)
            if not stock:
                stock = stock_data.get("stock", {}).get(str(item_id), 0)
            return f"库存: {stock}" if stock > 0 else "[red]售罄[/red]"
    except Exception:
        pass
    return "[yellow]查询失败[/yellow]"


def cmd_grab(args, api, config):
    """执行抢购"""
    engine = GrabEngine(api, config)

    # 参数设置
    if args.item_id:
        item_id = int(args.item_id)
    else:
        item_id_str = config.grab.item_id or Prompt.ask("[yellow]请输入装扮商品ID[/yellow]")
        try:
            item_id = int(item_id_str)
        except ValueError:
            console.print("[red]✗ 商品ID必须是数字[/red]")
            return

    num = args.num or config.grab.num

    # 确认信息
    console.print(Panel(
        f"[bold]抢购配置确认[/bold]\n\n"
        f"商品ID: [cyan]{item_id}[/cyan]\n"
        f"数量: [green]{num}[/green]\n"
        f"模式: [yellow]{'定时抢购' if args.mode != 'watch' else '监控补货'}[/yellow]",
        title="🎯 抢购确认",
    ))

    # 检查库存
    stock_info = get_stock_status(api, item_id)
    console.print(f"[dim]当前{stock_info}[/dim]")

    if args.mode == "watch":
        # 监控模式
        if not args.force:
            if not Confirm.ask("[yellow]启动监控模式？检测到库存≥1时自动抢购[/yellow]"):
                console.print("[yellow]已取消[/yellow]")
                return

        engine.watch_and_grab(
            item_id=item_id,
            num=num,
            check_interval=args.interval or 3.0,
            trigger_stock=1,
            concurrent_workers=args.concurrent or config.grab.concurrent_workers,
            on_status=lambda msg: console.print(msg),
        )
    else:
        # 定时抢购模式
        sale_time = args.time or config.grab.sale_time

        if not sale_time:
            sale_time = Prompt.ask("[yellow]请输入开售时间 (格式: 2025-01-01 20:00:00)[/yellow]")

        console.print(f"[cyan]等待开售时间: {sale_time}[/cyan]")

        if not args.force:
            if not Confirm.ask("[yellow]确认启动抢购？[/yellow]"):
                console.print("[yellow]已取消[/yellow]")
                return

        result = engine.grab_at_time(
            sale_time=sale_time,
            item_id=item_id,
            num=num,
            advance_seconds=args.advance or config.grab.advance_seconds,
            max_retries=args.retries or config.grab.max_retries,
            retry_interval=args.interval or config.grab.retry_interval,
            concurrent_workers=args.concurrent or config.grab.concurrent_workers,
            on_status=lambda msg: console.print(msg),
        )

    # 显示结果
    result = engine.last_result
    console.print()
    if result.success:
        console.print(Panel(
            f"[bold green]🎉 抢购成功！[/bold green]\n\n"
            f"订单号: [cyan]{result.order_id}[/cyan]\n"
            f"尝试次数: {result.attempts}\n"
            f"耗时: [green]{result.elapsed:.2f}秒[/green]",
            title="✅ 成功",
            border_style="green",
        ))
    else:
        console.print(Panel(
            f"[bold red]😢 抢购失败[/bold red]\n\n"
            f"尝试次数: {result.attempts}\n"
            f"耗时: {result.elapsed:.2f}秒\n"
            f"原因: [red]{result.message}[/red]",
            title="❌ 失败",
            border_style="red",
        ))


def cmd_config(args, api, config):
    """配置管理"""
    if args.show:
        # 显示当前配置
        console.print(Panel(
            f"[bold]当前配置[/bold]\n\n"
            f"商品ID: [cyan]{config.grab.item_id or '(未设置)'}[/cyan]\n"
            f"购买数量: {config.grab.num}\n"
            f"开售时间: {config.grab.sale_time or '(未设置)'}\n"
            f"提前秒数: {config.grab.advance_seconds}秒\n"
            f"并发数: {config.grab.concurrent_workers}\n"
            f"最大重试: {config.grab.max_retries}\n"
            f"重试间隔: {config.grab.retry_interval}秒\n"
            f"通知: {'启用' if config.notify.enabled else '禁用'}",
            title="⚙️ 配置",
        ))

    elif args.set:
        # 设置配置项
        key, value = args.set.split("=", 1)
        key = key.strip()
        value = value.strip()

        # 映射到配置
        if key == "item_id":
            config.grab.item_id = value
        elif key == "num":
            config.grab.num = int(value)
        elif key == "sale_time":
            config.grab.sale_time = value
        elif key == "advance":
            config.grab.advance_seconds = float(value)
        elif key == "concurrent":
            config.grab.concurrent_workers = int(value)
        elif key == "retries":
            config.grab.max_retries = int(value)
        elif key == "interval":
            config.grab.retry_interval = float(value)
        else:
            console.print(f"[red]未知配置项: {key}[/red]")
            console.print("[yellow]支持的配置项: item_id, num, sale_time, advance, concurrent, retries, interval[/yellow]")
            return

        save_config(config)
        console.print(f"[green]✓ 已设置 {key}={value}[/green]")


def cmd_stock(args, api, config):
    """查询库存"""
    if args.item_id:
        item_ids = [int(i) for i in args.item_id.split(",")]
    else:
        item_id_str = Prompt.ask("[yellow]请输入装扮商品ID (多个用逗号分隔)[/yellow]")
        try:
            item_ids = [int(i.strip()) for i in item_id_str.split(",")]
        except ValueError:
            console.print("[red]✗ 商品ID格式错误[/red]")
            return

    console.print(f"[cyan]正在查询库存...[/cyan]")

    try:
        stock_data = api.get_suit_stock(item_ids)
        table = Table(title="📦 库存查询", box=box.ROUNDED)
        table.add_column("商品ID", style="cyan")
        table.add_column("库存", style="yellow")
        table.add_column("状态", style="green")

        for item_id in item_ids:
            stock = stock_data.get(str(item_id), 0)
            if isinstance(stock_data, dict) and "stock" in stock_data:
                stock = stock_data["stock"].get(str(item_id), stock)
            status = "有货 ✅" if stock and stock > 0 else "售罄 ❌"
            table.add_row(str(item_id), str(stock), status)

        console.print(table)

    except BiliApiError as e:
        console.print(f"[red]✗ 查询失败: {e}[/red]")


def cmd_account(args, api, config):
    """查看账户信息"""
    console.print("[cyan]正在查询账户信息...[/cyan]")

    # 检查登录
    try:
        user_info = api.check_login()
        if not user_info.get("isLogin"):
            console.print("[red]✗ 未登录，请先执行 login 命令登录[/red]")
            return

        console.print(Panel(
            f"[bold]用户信息[/bold]\n\n"
            f"昵称: [green]{user_info.get('uname', '未知')}[/green]\n"
            f"UID: [cyan]{user_info.get('mid', '未知')}[/cyan]\n"
            f"等级: {user_info.get('level_info', {}).get('current_level', '?')}\n"
            f"硬币: {user_info.get('money', 0)}",
            title="👤 账户信息",
        ))
    except BiliApiError as e:
        console.print(f"[red]✗ 查询失败: {e}[/red]")


def cmd_url(args, api, config):
    """从链接解析活动/装扮信息"""
    info = parse_activity_url(args.page_url, api=api)

    if not info.parsed:
        console.print(f"[red]✗ {info.error}[/red]")
        return

    console.print(Panel(
        f"[bold cyan]🔗 URL 解析结果[/bold cyan]\n\n"
        f"链接: {info.url[:80]}...\n"
        f"类型: [yellow]{'数字卡片(DLC)' if info.kind == 'dlc' else info.kind or '未知'}[/yellow]\n"
        f"活动ID: [cyan]{info.act_id or '未提取到'}[/cyan]\n"
        f"抽奖ID: [cyan]{info.lottery_id or '无'}[/cyan]\n"
        f"名称: [green]{info.name or '未获取到'}[/green]\n"
        f"开售时间: [yellow]{info.sale_time or '未获取到（需手动指定）'}[/yellow]",
        title="URL 解析",
    ))

    # 提示下一步
    if info.kind == "dlc":
        console.print("\n[dim]💡 下一步: python main.py dlc --url \"URL\" --time \"开售时间\"[/dim]")
    else:
        console.print("\n[dim]💡 下一步: python main.py grab -i {id} -t \"开售时间\"[/dim]".format(id=info.act_id or 'ID'))


def main():
    """主入口"""
    config = load_config()
    api = BiliAPI(config)

    parser = argparse.ArgumentParser(
        description="🎨 B站装扮抢购工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python main.py login cookie "SESSDATA=xxx; bili_jct=xxx"
  python main.py login status
  python main.py info 12345
  python main.py search "初音未来"
  python main.py list
  python main.py grab --item-id 12345 --time "2025-01-01 20:00:00"
  python main.py grab --item-id 12345 --mode watch
  python main.py stock 12345
  python main.py config --show
  python main.py config --set item_id=12345
        """,
    )
    parser.add_argument("--no-banner", action="store_true", help="不显示Banner")

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # login
    p_login = subparsers.add_parser("login", help="登录管理")
    p_login.add_argument("method", choices=["cookie", "qrcode", "browser", "quick", "status"],
                        help="登录方式 (cookie/qrcode/browser/status)")
    p_login.add_argument("value", nargs="?", help="Cookie字符串 (仅cookie方式)")

    # info
    p_info = subparsers.add_parser("info", help="查询装扮详情")
    p_info.add_argument("item_id", nargs="?", help="装扮商品ID")

    # search
    p_search = subparsers.add_parser("search", help="搜索装扮")
    p_search.add_argument("keyword", nargs="?", help="搜索关键词")

    # list
    p_list = subparsers.add_parser("list", help="查看在售装扮列表")
    p_list.add_argument("--page", "-p", type=int, default=1, help="页码")

    # grab
    p_grab = subparsers.add_parser("grab", help="执行抢购")
    p_grab.add_argument("--item-id", "-i", help="装扮商品ID")
    p_grab.add_argument("--num", "-n", type=int, default=0, help="购买数量")
    p_grab.add_argument("--time", "-t", help="开售时间 (格式: 2025-01-01 20:00:00)")
    p_grab.add_argument("--mode", "-m", choices=["once", "watch"], default="once",
                       help="抢购模式: once=定时抢购, watch=监控补货")
    p_grab.add_argument("--advance", "-a", type=float, default=0,
                       help="提前发起秒数 (默认: 配置值)")
    p_grab.add_argument("--retries", "-r", type=int, default=0,
                       help="最大重试次数")
    p_grab.add_argument("--interval", "-d", type=float, default=0,
                       help="重试间隔(秒) / 监控检查间隔")
    p_grab.add_argument("--concurrent", "-c", type=int, default=0,
                       help="并发工作数")
    p_grab.add_argument("--force", "-f", action="store_true",
                       help="跳过确认")

    # stock
    p_stock = subparsers.add_parser("stock", help="查询库存")
    p_stock.add_argument("item_id", nargs="?", help="装扮商品ID (多个用逗号分隔)")

    # account
    subparsers.add_parser("account", help="查看账户信息")

    # dlc (数字卡片)
    p_dlc = subparsers.add_parser("dlc", help="数字卡片抢购")
    p_dlc.add_argument("--act-id", type=int, default=113353, help="活动ID")
    p_dlc.add_argument("--lottery-id", "-l", type=int, default=113354, help="抽奖ID")
    p_dlc.add_argument("--time", "-t", help="开售时间 (格式: 2025-01-01 20:00:00)")
    p_dlc.add_argument("--concurrent", "-c", type=int, default=0, help="并发数")
    p_dlc.add_argument("--retries", "-r", type=int, default=0, help="最大重试次数")
    p_dlc.add_argument("--advance", "-a", type=float, default=0, help="提前秒数")
    p_dlc.add_argument("--interval", "-d", type=float, default=0, help="重试间隔")
    p_dlc.add_argument("--watch", "-w", action="store_true", help="监控模式（持续检查库存）")
    p_dlc.add_argument("--force", "-f", action="store_true", help="跳过确认")
    p_dlc.add_argument("--url", "-u", help="活动页面 URL，自动提取 act_id/lottery_id")

    # url（URL 解析）
    p_url = subparsers.add_parser("url", help="从活动链接自动解析商品ID和参数")
    p_url.add_argument("page_url", help="B站活动/装扮页面完整 URL")

    # config
    p_config = subparsers.add_parser("config", help="配置管理")
    p_config.add_argument("--show", "-s", action="store_true", help="显示配置")
    p_config.add_argument("--set", help="设置配置项 (格式: key=value)")

    args = parser.parse_args()

    if not args.no_banner:
        console.print(BANNER, style="cyan")

    if not args.command:
        parser.print_help()
        console.print("\n[bold yellow]快速开始:[/bold yellow]")
        console.print(" 1. 登录:   [cyan]python main.py login cookie \"SESSDATA=xxx; bili_jct=xxx\"[/cyan]")
        console.print(" 2. 搜索:   [cyan]python main.py search \"装扮名\"[/cyan]")
        console.print(" 3. 抢购:   [cyan]python main.py grab -i 12345 -t \"2025-01-01 20:00:00\" -c 8[/cyan]")
        return

    # 命令路由
    commands = {
        "login": lambda: cmd_login(args, api, config),
        "info": lambda: cmd_info(args, api, config),
        "search": lambda: cmd_search(args, api, config),
        "list": lambda: cmd_list(args, api, config),
        "grab": lambda: cmd_grab(args, api, config),
        "config": lambda: cmd_config(args, api, config),
        "stock": lambda: cmd_stock(args, api, config),
        "account": lambda: cmd_account(args, api, config),
        "url": lambda: cmd_url(args, api, config),
    }
    commands["dlc"] = lambda: cmd_dlc(args, api, config)

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func()
    else:
        parser.print_help()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        console.print("[yellow]已退出[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"[red]发生错误: {e}[/red]")
        if os.environ.get("DEBUG"):
            import traceback
            traceback.print_exc()
        sys.exit(1)