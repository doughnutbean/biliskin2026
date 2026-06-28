"""抢购核心引擎 - 定时抢购、异步并发、重试逻辑"""

import asyncio
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Callable

from api import BiliAPI, BiliApiError
from config import AppConfig


class GrabResult:
    """一次抢购的结果"""

    def __init__(self):
        self.success: bool = False
        self.attempts: int = 0
        self.elapsed: float = 0.0
        self.order_id: str = ""
        self.message: str = ""
        self.snapshot_times: list[float] = []  # 请求发起时间戳列表

    def __str__(self) -> str:
        if self.success:
            return (
                f"[✓] 抢购成功！\n"
                f"    尝试次数: {self.attempts}\n"
                f"    耗时: {self.elapsed:.2f}秒\n"
                f"    订单号: {self.order_id}\n"
                f"    信息: {self.message}"
            )
        else:
            return (
                f"[✗] 抢购失败\n"
                f"    尝试次数: {self.attempts}\n"
                f"    耗时: {self.elapsed:.2f}秒\n"
                f"    原因: {self.message}"
            )


class GrabEngine:
    """抢购引擎"""

    def __init__(self, api: BiliAPI, config: AppConfig):
        self.api = api
        self.config = config
        self._running = False
        self._result = GrabResult()

    # ──────────────── 单次下单（同步） ────────────────

    def buy_once(self, item_id: int, num: int = 1) -> GrabResult:
        """单次购买尝试（同步）"""
        result = GrabResult()
        try:
            data = self.api.create_order(item_id, num)
            result.success = True
            result.attempts = 1
            result.order_id = data.get("order_id", str(data.get("trade_id", "")))
            result.message = "下单成功"
        except BiliApiError as e:
            result.message = str(e)
            result.attempts = 1
        except Exception as e:
            result.message = f"未知错误: {e}"
            result.attempts = 1
        return result

    # ──────────────── 异步并发抢购 ────────────────

    async def _async_buy_worker(
        self,
        item_id: int,
        num: int,
        worker_id: int,
    ) -> Optional[dict]:
        """单个异步工作线程"""
        try:
            data = await self.api.async_create_order(item_id, num)
            return data
        except BiliApiError as e:
            # 如果是库存不足，静默跳过
            if "库存不足" in str(e) or "已售罄" in str(e):
                return None
            return None
        except Exception:
            return None

    async def _async_buy_batch(
        self,
        item_id: int,
        num: int,
        concurrency: int,
        snapshot_times: list,
    ) -> Optional[dict]:
        """并发发起一批购买请求"""
        now = time.time()
        snapshot_times.append(now)

        tasks = [
            self._async_buy_worker(item_id, num, i)
            for i in range(concurrency)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 取第一个成功的结果
        for r in results:
            if isinstance(r, dict) and r is not None:
                return r
        return None

    def _run_async_batch(
        self,
        item_id: int,
        num: int,
        concurrency: int,
        snapshot_times: list,
    ) -> Optional[dict]:
        """同步包装器，运行异步并发批处理"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                self._async_buy_batch(item_id, num, concurrency, snapshot_times)
            )
        finally:
            loop.close()

    # ──────────────── 定时抢购 ────────────────

    def grab_at_time(
        self,
        sale_time: str,
        item_id: int,
        num: int = 1,
        advance_seconds: float = 0.5,
        max_retries: int = 20,
        retry_interval: float = 0.5,
        concurrent_workers: int = 8,
        on_status: Optional[Callable[[str], None]] = None,
        on_tick: Optional[Callable[[dict], None]] = None,
    ) -> GrabResult:
        """在指定时间发起抢购

        Args:
            sale_time: 开售时间，格式 "2025-01-01 20:00:00"
            item_id: 装扮商品ID
            num: 购买数量
            advance_seconds: 提前发起的时间（秒）
            max_retries: 最大重试次数
            retry_interval: 重试间隔（秒）
            concurrent_workers: 并发工作线程数
            on_status: 状态回调
            on_tick: 每次尝试后的回调

        Returns:
            抢购结果
        """
        self._result = GrabResult()
        target = self._parse_time(sale_time)
        if target is None:
            self._result.message = f"时间格式错误: {sale_time}"
            return self._result

        self._log(on_status, f"[*] 抢购目标: {sale_time}")
        self._log(on_status, f"[*] 商品ID: {item_id}, 数量: {num}")
        self._log(on_status, f"[*] 并发数: {concurrent_workers}, 最大重试: {max_retries}")
        self._log(on_status, f"[*] 等待开售...")

        # 等待到开售前
        self._wait_until_precise(target, advance_seconds)

        start_time = time.time()
        self._running = True

        for attempt in range(1, max_retries + 1):
            if not self._running:
                self._result.message = "抢购被中断"
                break

            try:
                if concurrent_workers > 1:
                    # 并发模式
                    data = self._run_async_batch(
                        item_id, num, concurrent_workers, self._result.snapshot_times
                    )
                else:
                    # 单线程模式
                    now = time.time()
                    self._result.snapshot_times.append(now)
                    data = self.api.create_order(item_id, num) if hasattr(self, '_sync_api') else None
                    if data is None:
                        # fallback
                        data = self._run_async_batch(
                            item_id, num, 1, self._result.snapshot_times
                        )

                self._result.attempts = attempt

                if data:
                    order_id = data.get("order_id", str(data.get("trade_id", "")))
                    self._result.success = True
                    self._result.order_id = order_id
                    self._result.elapsed = time.time() - start_time
                    self._result.message = f"第{attempt}次尝试成功!"
                    self._log(on_status, f"[✓] 抢购成功！订单号: {order_id}")

                    if on_tick:
                        on_tick({
                            "status": "success",
                            "attempt": attempt,
                            "order_id": order_id,
                            "elapsed": self._result.elapsed,
                        })
                    return self._result
                else:
                    if attempt < max_retries:
                        self._log(on_status, f"[~] 第{attempt}次尝试未成功，{retry_interval}秒后重试...")
                        if on_tick:
                            on_tick({
                                "status": "retry",
                                "attempt": attempt,
                                "delay": retry_interval,
                            })
                        time.sleep(retry_interval)

            except BiliApiError as e:
                self._result.attempts = attempt
                err_msg = str(e)

                if "库存不足" in err_msg or "已售罄" in err_msg:
                    if attempt < max_retries:
                        self._log(on_status, f"[~] 库存不足，第{attempt}次尝试，{retry_interval}秒后重试...")
                        if on_tick:
                            on_tick({
                                "status": "out_of_stock",
                                "attempt": attempt,
                                "delay": retry_interval,
                            })
                        time.sleep(retry_interval)
                    else:
                        self._result.message = f"库存不足（已重试{max_retries}次）"
                else:
                    if attempt < max_retries:
                        self._log(on_status, f"[~] 错误: {err_msg}，第{attempt}次尝试，立即重试...")
                        time.sleep(retry_interval)
                    else:
                        self._result.message = f"错误: {err_msg}（已重试{max_retries}次）"
                        self._result.elapsed = time.time() - start_time

            except Exception as e:
                self._result.attempts = attempt
                err_msg = str(e)
                if attempt < max_retries:
                    self._log(on_status, f"[~] 异常: {err_msg}，第{attempt}次尝试，立即重试...")
                    time.sleep(retry_interval)
                else:
                    self._result.message = f"异常: {err_msg}"
                    self._result.elapsed = time.time() - start_time

        if not self._result.success:
            self._result.elapsed = time.time() - start_time
            if not self._result.message:
                self._result.message = f"已用尽{max_retries}次尝试"
            self._log(on_status, f"[✗] 抢购失败: {self._result.message}")

        return self._result

    # ──────────────── 监控模式 ────────────────

    def watch_and_grab(
        self,
        item_id: int,
        num: int = 1,
        check_interval: float = 3.0,
        trigger_stock: int = 1,
        concurrent_workers: int = 8,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> GrabResult:
        """监控库存，有货即抢（用于补货场景）

        Args:
            item_id: 装扮商品ID
            num: 购买数量
            check_interval: 库存检查间隔（秒）
            trigger_stock: 库存大于等于此值触发抢购
            concurrent_workers: 并发数
            on_status: 状态回调
        """
        self._result = GrabResult()
        self._running = True
        self._log(on_status, f"[*] 启动监控模式，商品ID: {item_id}")
        self._log(on_status, f"[*] 检查间隔: {check_interval}秒，触发库存: ≥{trigger_stock}")

        while self._running:
            try:
                stock_data = self.api.get_suit_stock([item_id])
                stock = 0

                # 解析库存数据
                if isinstance(stock_data, dict):
                    # 可能的结构: {item_id: stock} 或 {"stock": {...}}
                    stock = stock_data.get(str(item_id), 0) or stock_data.get("stock", {}).get(str(item_id), 0)

                now = datetime.now().strftime("%H:%M:%S")
                if stock >= trigger_stock:
                    self._log(on_status, f"[!] [{now}] 检测到库存: {stock}，立即抢购！")
                    return self.grab_at_time(
                        sale_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        item_id=item_id,
                        num=num,
                        advance_seconds=0,
                        max_retries=30,
                        retry_interval=0.3,
                        concurrent_workers=concurrent_workers,
                        on_status=on_status,
                    )
                else:
                    if stock > 0:
                        self._log(on_status, f"[~] [{now}] 当前库存: {stock}，未达到触发值")
                    time.sleep(check_interval)

            except BiliApiError as e:
                self._log(on_status, f"[~] 查询库存失败: {e}，{check_interval}秒后重试")
                time.sleep(check_interval)
            except KeyboardInterrupt:
                self._running = False
                self._result.message = "用户中断"
                break

        return self._result

    def stop(self) -> None:
        """停止抢购"""
        self._running = False

    # ──────────────── 工具方法 ────────────────

    def _parse_time(self, time_str: str) -> Optional[datetime]:
        """解析时间字符串"""
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%m-%d %H:%M:%S",
            "%H:%M:%S",
        ]
        for fmt in formats:
            try:
                t = datetime.strptime(time_str, fmt)
                # 对于不含年份的格式，补全年份
                if "%Y" not in fmt:
                    t = t.replace(year=datetime.now().year)
                # 对于只含时间的格式，补全日期
                if fmt == "%H:%M:%S":
                    t = t.replace(
                        year=datetime.now().year,
                        month=datetime.now().month,
                        day=datetime.now().day,
                    )
                    # 如果时间已过，说明是第二天
                    if t < datetime.now():
                        t += timedelta(days=1)
                return t
            except ValueError:
                continue
        return None

    def _wait_until_precise(self, target: datetime, advance: float) -> None:
        """精确等待到指定时间（提前advance秒发起）
        使用忙等待实现毫秒级精度
        """
        target_ts = target.timestamp() - advance
        now_ts = time.time()

        if target_ts <= now_ts:
            # 时间已过，立即执行
            return

        # 第一阶段：提前1秒以上，使用sleep
        wait_time = target_ts - now_ts - 1.0
        if wait_time > 0:
            time.sleep(wait_time)

        # 第二阶段：最后1秒，忙等待到微秒级精度
        while time.time() < target_ts:
            pass

    def _log(self, callback: Optional[Callable], msg: str) -> None:
        """输出日志"""
        if callback:
            callback(msg)
        else:
            print(msg)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_result(self) -> GrabResult:
        return self._result
