"""数字卡片抢购脚本 - 针对鸣潮2周年同人绘画"""
import json, time, asyncio, sys
from datetime import datetime, timedelta
from config import load_config, save_config
from api import BiliAPI, BiliApiError
from graber import GrabResult

# 活动参数
ACT_ID = 113353
LOTTERY_ID = 113354
SALE_TIME_STR = "2026-06-28 17:00:00"
CONCURRENT = 8
MAX_RETRIES = 30
ADVANCE_SECONDS = 0.5


def precise_wait(target_ts: float, advance: float):
    """精确等待到目标时间"""
    fire_ts = target_ts - advance
    now_ts = time.time()
    if fire_ts <= now_ts:
        return
    wait = fire_ts - now_ts - 1.0
    if wait > 0:
        print(f"[*] 等待 {wait:.1f} 秒...")
        time.sleep(wait)
    while time.time() < fire_ts:
        pass


async def async_buy(api: BiliAPI, worker_id: int) -> dict:
    """异步尝试购买（抽数字卡片）"""
    csrf = api.get_csrf_token()
    url = f"{api.config.bilibili.base_url}/x/garb/trade/create"

    # 构建请求
    headers = {
        "User-Agent": api.config.bilibili.user_agent,
        "Referer": f"https://www.bilibili.com/blackboard/activity-Mz9T5bO5Q3.html?type=dlc&id={ACT_ID}&lottery_id={LOTTERY_ID}",
        "Origin": "https://www.bilibili.com",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    # 尝试用不同参数组合
    payloads = [
        {"item_id": LOTTERY_ID, "num": 1, "csrf": csrf},
        {"item_id": ACT_ID, "num": 1, "csrf": csrf},
    ]

    import httpx
    async with httpx.AsyncClient(headers=headers, timeout=10, follow_redirects=True) as client:
        for ck, cv in api._session.cookies.items():
            client.cookies.set(ck, cv)

        for payload in payloads:
            try:
                resp = await client.post(url, data=payload)
                data = resp.json()
                if data.get("code") == 0:
                    return data.get("data", {})
            except:
                continue
    return None


def run_grab():
    """执行抢购"""
    config = load_config()
    api = BiliAPI(config)

    # 验证登录
    nav = api.check_login()
    if not nav.get("isLogin"):
        print("[✗] 未登录！请先通过 main.py login cookie 登录")
        return

    print(f"[✓] 用户: {nav.get('uname')} (UID: {nav.get('mid')})")
    print(f"[*] 活动ID: {ACT_ID}, 抽奖ID: {LOTTERY_ID}")
    print(f"[*] 开售时间: {SALE_TIME_STR}")

    # 解析开售时间
    target = datetime.strptime(SALE_TIME_STR, "%Y-%m-%d %H:%M:%S")
    target_ts = target.timestamp()

    # 等待
    precise_wait(target_ts, ADVANCE_SECONDS)

    print(f"[*] 开售！发起购买请求...")
    start = time.time()
    result = GrabResult()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            tasks = [async_buy(api, i) for i in range(CONCURRENT)]
            results = loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            loop.close()

            result.attempts = attempt
            now = time.time()
            result.snapshot_times.append(now)

            for r in results:
                if isinstance(r, dict) and r:
                    order_id = r.get("order_id", r.get("trade_id", ""))
                    result.success = True
                    result.order_id = str(order_id)
                    result.elapsed = now - start
                    result.message = f"第{attempt}次尝试成功!"
                    print(f"\n[✓] 下单成功！")
                    print(f"    订单号: {order_id}")
                    print(f"    耗时: {result.elapsed:.2f}秒")
                    print(f"    尝试次数: {attempt}")
                    print(f"    完整响应: {json.dumps(r, ensure_ascii=False)[:300]}")
                    return result

            # 没成功
            print(f"[~] 第{attempt}次尝试未成功，0.5秒后重试...")
            time.sleep(0.5)

        except Exception as e:
            print(f"[~] 第{attempt}次出错: {e}")
            time.sleep(0.5)

    result.elapsed = time.time() - start
    result.message = f"已用尽{MAX_RETRIES}次尝试"
    print(f"\n[✗] 抢购失败: {result.message}")
    return result


if __name__ == "__main__":
    try:
        run_grab()
    except KeyboardInterrupt:
        print("\n[yellow]已退出[/yellow]")
        sys.exit(0)
