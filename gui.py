#!/usr/bin/env python3
"""B站数字卡片抢购工具 - 图形界面版"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import time
import asyncio
import json
import sys
import os
from datetime import datetime, timedelta

# 添加项目根目录到path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config, save_config
# 注意：BiliAPI 和 LoginManager 延迟到使用时导入，避免 exe 启动时
# 加载 httpx/requests 等重量级 HTTP 库导致窗口出现缓慢


class GrabApp:
    def __init__(self, root):
        self.root = root
        self.root.title("B站数字卡片抢购工具")
        self.root.geometry("720x680")
        self.root.resizable(False, False)

        # 设置样式
        style = ttk.Style()
        style.theme_use("vista")

        # 状态变量
        self.running = False
        self.login_status = tk.StringVar(value="未登录")
        self.act_id = tk.StringVar(value="113353")
        self.lottery_id = tk.StringVar(value="113354")
        self.sale_time = tk.StringVar(value="2026-06-28 17:00:00")
        self.concurrent = tk.StringVar(value="8")
        self.advance = tk.StringVar(value="0.5")
        self.retries = tk.StringVar(value="30")
        self.pay_type = tk.StringVar(value="bp")

        # 加载配置（延迟导入 BiliAPI，避免 exe 启动时加载 httpx）
        from api import BiliAPI
        self.config = load_config()
        self.api = BiliAPI(self.config)

        self._build_ui()
        self._check_login()

    def _build_ui(self):
        """构建UI"""
        # 标题
        title_frame = tk.Frame(self.root, bg="#fb7299", height=60)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)

        tk.Label(title_frame, text="🎨 B站数字卡片抢购工具",
                 fg="white", bg="#fb7299",
                 font=("Microsoft YaHei", 16, "bold")).pack(pady=10)

        # 主容器
        main = tk.Frame(self.root, padx=20, pady=15)
        main.pack(fill=tk.BOTH, expand=True)

        # === 登录状态栏 ===
        login_frame = tk.LabelFrame(main, text="登录状态", font=("Microsoft YaHei", 10))
        login_frame.pack(fill=tk.X, pady=(0, 10))

        row1 = tk.Frame(login_frame)
        row1.pack(fill=tk.X, padx=10, pady=8)

        tk.Label(row1, textvariable=self.login_status,
                 font=("Microsoft YaHei", 10)).pack(side=tk.LEFT)
        tk.Button(row1, text="刷新", command=self._check_login,
                  bg="#00a1d6", fg="white").pack(side=tk.RIGHT, padx=5)
        self.quick_login_btn = tk.Button(row1, text="🔑 一键登录",
                                         command=self._start_quick_login,
                                         bg="#fb7299", fg="white",
                                         font=("Microsoft YaHei", 9))
        self.quick_login_btn.pack(side=tk.RIGHT, padx=5)

        # === 参数配置栏 ===
        config_frame = tk.LabelFrame(main, text="抢购参数", font=("Microsoft YaHei", 10))
        config_frame.pack(fill=tk.X, pady=(0, 10))

        grid = tk.Frame(config_frame)
        grid.pack(padx=10, pady=10)

        fields = [
            ("活动ID:", self.act_id, 0, 0),
            ("抽奖ID:", self.lottery_id, 0, 2),
            ("开售时间:", self.sale_time, 1, 0),
            ("并发数:", self.concurrent, 1, 2),
            ("提前秒数:", self.advance, 2, 0),
            ("重试次数:", self.retries, 2, 2),
        ]

        for text, var, row, col in fields:
            tk.Label(grid, text=text, font=("Microsoft YaHei", 9)).grid(
                row=row, column=col, sticky=tk.W, padx=(0 if col == 2 else 20, 5), pady=4)
            tk.Entry(grid, textvariable=var, width=18,
                     font=("Microsoft YaHei", 9)).grid(
                row=row, column=col + 1, padx=(0, 20 if col == 0 else 0))

        # 支付方式
        tk.Label(grid, text="支付方式:", font=("Microsoft YaHei", 9)).grid(
            row=3, column=0, sticky=tk.W, padx=0, pady=4)
        pay_frame = tk.Frame(grid)
        pay_frame.grid(row=3, column=1, sticky=tk.W, pady=4)
        tk.Radiobutton(pay_frame, text="B币支付", variable=self.pay_type,
                       value="bp", font=("Microsoft YaHei", 9)).pack(side=tk.LEFT)
        tk.Radiobutton(pay_frame, text="硬币支付", variable=self.pay_type,
                       value="coin", font=("Microsoft YaHei", 9)).pack(side=tk.LEFT, padx=10)

        # 倒计时
        self.countdown_var = tk.StringVar(value="")
        tk.Label(grid, textvariable=self.countdown_var,
                 font=("Microsoft YaHei", 9), fg="#fb7299").grid(
            row=3, column=2, columnspan=2, sticky=tk.W, padx=10)

        # 从链接导入
        import_frame = tk.Frame(config_frame)
        import_frame.pack(fill=tk.X, padx=10, pady=(0, 8))
        tk.Label(import_frame, text="🔗 从链接导入:",
                 font=("Microsoft YaHei", 9)).pack(side=tk.LEFT)
        self.url_entry = tk.Entry(import_frame, font=("Microsoft YaHei", 9))
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        tk.Button(import_frame, text="导入", command=self._import_from_url,
                  bg="#00a1d6", fg="white",
                  font=("Microsoft YaHei", 9)).pack(side=tk.LEFT)

        # === 控制按钮 ===
        btn_frame = tk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=5)

        self.start_btn = tk.Button(btn_frame, text="🚀 开始抢购",
                                   command=self._start_grab,
                                   bg="#fb7299", fg="white",
                                   font=("Microsoft YaHei", 11, "bold"),
                                   width=15, height=1)
        self.start_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = tk.Button(btn_frame, text="⏹ 停止",
                                  command=self._stop_grab,
                                  bg="#888", fg="white",
                                  font=("Microsoft YaHei", 11),
                                  width=10, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        # === 日志输出框 ===
        log_frame = tk.LabelFrame(main, text="运行日志", font=("Microsoft YaHei", 10))
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD,
            font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="white", height=15)
        self.log.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 日志标签颜色
        self.log.tag_config("info", foreground="#569cd6")
        self.log.tag_config("success", foreground="#4ec9b0")
        self.log.tag_config("warning", foreground="#ce9178")
        self.log.tag_config("error", foreground="#f44747")
        self.log.tag_config("bold", font=("Consolas", 9, "bold"))

    def _log(self, msg, tag="info"):
        """输出日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log.insert(tk.END, f"[{timestamp}] ", "info")
        self.log.insert(tk.END, msg + "\n", tag)
        self.log.see(tk.END)
        self.root.update_idletasks()

    def _check_login(self):
        """检查登录状态"""
        try:
            nav = self.api.check_login()
            if nav.get("isLogin"):
                uname = nav.get("uname", "未知")
                uid = nav.get("mid", 0)
                self.login_status.set(f"✅ 已登录 | {uname} (UID: {uid})")
                self._log(f"✓ 登录成功: {uname}", "success")
            else:
                self.login_status.set("❌ 未登录")
                self._log("✗ 未登录，请先通过 main.py 登录", "error")
        except Exception as e:
            self.login_status.set(f"❌ 登录失效: {e}")
            self._log(f"✗ 登录检查失败: {e}", "error")

    def _import_from_url(self):
        """从活动链接导入抢购参数"""
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("提示", "请先粘贴活动页面链接")
            return

        from url_parser import parse_activity_url
        info = parse_activity_url(url, api=self.api)

        if not info.parsed:
            messagebox.showerror("解析失败", info.error or "无法从链接提取商品信息")
            return

        # 自动填充参数
        if info.act_id:
            self.act_id.set(str(info.act_id))
        if info.lottery_id:
            self.lottery_id.set(str(info.lottery_id))
        if info.sale_time:
            self.sale_time.set(info.sale_time)
        if info.name:
            self._log(f"📦 导入: {info.name}", "success")

        self._log(f"🔗 从链接导入成功！类型: {'DLC数字卡片' if info.kind == 'dlc' else info.kind}", "success")
        self._log(f"   活动ID: {info.act_id}, 抽奖ID: {info.lottery_id}, 时间: {info.sale_time or '需手动填写'}", "info")

    def _start_quick_login(self):
        """一键登录：后台线程中先浏览器提取 → 失败则扫码"""
        self.quick_login_btn.config(state=tk.DISABLED, text="登录中...")
        self._log("🔑 一键登录：正在从浏览器提取 B站 Cookie...", "bold")

        def status_callback(msg):
            """将登录进度消息转发到 GUI 日志和状态栏"""
            # 检测二维码 URL（扫码登录时返回）
            if msg.startswith("__QRCODE_URL__:"):
                qr_url = msg.split(":", 1)[1]
                self.root.after(0, lambda u=qr_url: self._show_qrcode_window(u))
                return
            # 扫码登录成功，关闭二维码窗口
            if msg == "__LOGIN_OK__":
                self.root.after(0, self._close_qrcode_window)
                return
            self.root.after(0, lambda m=msg: self._log(m, "info"))

        def run_login():
            from login import LoginManager
            login_mgr = LoginManager(self.api, self.config)
            success, method = login_mgr.login_quick(status_callback=status_callback)
            # 回到主线程更新 UI
            if success:
                self.root.after(0, lambda: [
                    self._log(f"✅ 登录成功！（方式: {method}）", "success"),
                    self._check_login(),
                    self.quick_login_btn.config(state=tk.NORMAL, text="🔑 一键登录"),
                ])
            else:
                self.root.after(0, lambda: [
                    self._log("❌ 登录失败，请重试", "error"),
                    self.quick_login_btn.config(state=tk.NORMAL, text="🔑 一键登录"),
                ])

        threading.Thread(target=run_login, daemon=True).start()

    def _show_qrcode_window(self, qr_url: str):
        """弹出窗口显示二维码图片，引导用户扫码"""
        try:
            import qrcode
            from PIL import Image, ImageTk
        except ImportError:
            self._log("[!] 显示二维码需要安装: pip install qrcode[pil]", "warning")
            self._log(f"[*] 请手动打开链接扫码: {qr_url}", "info")
            return

        qr_win = tk.Toplevel(self.root)
        self._qr_win = qr_win  # 保存引用，供扫码成功后自动关闭
        qr_win.title("📱 请使用B站App扫码登录")
        qr_win.resizable(False, False)
        qr_win.transient(self.root)
        qr_win.grab_set()

        # 窗口尺寸：B站扫码 URL 可能更长，预留充裕空间
        win_w, win_h = 550, 600
        qr_win.geometry(f"{win_w}x{win_h}")

        # 居中到屏幕
        qr_win.update_idletasks()
        sw = qr_win.winfo_screenwidth()
        sh = qr_win.winfo_screenheight()
        x = (sw - win_w) // 2
        y = (sh - win_h) // 2
        qr_win.geometry(f"+{x}+{y}")

        # 顶部提示
        tk.Label(qr_win, text="请使用 B站App 扫描二维码",
                 font=("Microsoft YaHei", 12, "bold"),
                 fg="#fb7299").pack(pady=15)

        # 生成二维码图片（加保护防止 qrcode 库版本兼容问题）
        try:
            qr = qrcode.QRCode(border=2, box_size=10)
            qr.add_data(qr_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="#fb7299", back_color="white")
            # qrcode 7.x 返回的是 Pillow Image，旧版可能不同
            if not hasattr(img, 'convert'):
                # 不是 PIL Image，尝试转换
                from PIL import Image as PILImage
                img = img.get_image() if hasattr(img, 'get_image') else PILImage.new('RGB', (1, 1))
            photo = ImageTk.PhotoImage(img)
        except Exception as e:
            self._log(f"[!] 二维码图片生成失败: {e}", "warning")
            # 降级：显示文本链接
            tk.Label(qr_win, text="请手动打开以下链接扫码:",
                     font=("Microsoft YaHei", 10), fg="#666").pack(pady=10)
            link_text = tk.Text(qr_win, height=3, width=40,
                               font=("Consolas", 9), wrap=tk.WORD)
            link_text.insert("1.0", qr_url)
            link_text.config(state=tk.DISABLED)
            link_text.pack(pady=5, padx=20)
            qr_win.after(0, lambda: None)  # 跳过图片显示
            photo = None

        if photo:
            img_label = tk.Label(qr_win, image=photo, bg="white")
            img_label.image = photo  # 保持引用
            img_label.pack(pady=10)

        # 状态提示
        status_label = tk.Label(qr_win, text="等待扫码中...",
                                font=("Microsoft YaHei", 10), fg="#666")
        status_label.pack(pady=5)

        # 关闭按钮
        def close_qr():
            qr_win.destroy()

        tk.Button(qr_win, text="关闭", command=close_qr,
                  bg="#888", fg="white", width=10).pack(pady=10)

        # 定时更新状态提示
        def update_status():
            if qr_win.winfo_exists():
                status_label.config(text="请在手机上确认登录...")
                qr_win.after(3000, lambda: status_label.config(
                    text="等待扫码中..." if qr_win.winfo_exists() else None))

        qr_win.after(5000, update_status)

    def _close_qrcode_window(self):
        """关闭二维码弹窗（扫码成功后自动调用）"""
        if hasattr(self, '_qr_win') and self._qr_win and self._qr_win.winfo_exists():
            self._qr_win.destroy()
            self._qr_win = None

    def _start_grab(self):
        """开始抢购"""
        if self.running:
            return

        # 验证输入
        try:
            act_id = int(self.act_id.get())
            lottery_id = int(self.lottery_id.get())
            concurrent = int(self.concurrent.get())
            advance = float(self.advance.get())
            retries = int(self.retries.get())
            sale_time = self.sale_time.get().strip()
            datetime.strptime(sale_time, "%Y-%m-%d %H:%M:%S")
        except ValueError as e:
            messagebox.showerror("参数错误", f"请检查参数格式: {e}")
            return

        # 禁用启动按钮
        self.start_btn.config(state=tk.DISABLED, bg="#888")
        self.stop_btn.config(state=tk.NORMAL, bg="#e74c3c")
        self.running = True

        self._log("=" * 50, "bold")
        self._log(f"🚀 抢购启动", "bold")
        self._log(f"  活动ID: {act_id}", "info")
        self._log(f"  抽奖ID: {lottery_id}", "info")
        self._log(f"  开售时间: {sale_time}", "info")
        self._log(f"  并发数: {concurrent}", "info")
        self._log(f"  支付方式: {'B币' if self.pay_type.get() == 'bp' else '硬币'}", "info")
        self._log(f"  提前秒数: {advance}s", "info")
        self._log(f"  重试次数: {retries}", "info")
        self._log("=" * 50, "bold")

        # 在线程中运行抢购
        thread = threading.Thread(
            target=self._grab_thread,
            args=(act_id, lottery_id, sale_time, concurrent, advance, retries),
            daemon=True,
        )
        thread.start()

        # 启动倒计时更新
        self._update_countdown(sale_time)

    def _update_countdown(self, sale_time_str):
        """更新倒计时"""
        def update():
            while self.running:
                try:
                    target = datetime.strptime(sale_time_str, "%Y-%m-%d %H:%M:%S")
                    now = datetime.now()
                    if now >= target:
                        self.countdown_var.set("🔥 开售中!")
                        return
                    delta = target - now
                    h, rem = divmod(int(delta.total_seconds()), 3600)
                    m, s = divmod(rem, 60)
                    self.countdown_var.set(
                        f"⏱ 倒计时: {h:02d}:{m:02d}:{s:02d}")
                    self.root.update_idletasks()
                except:
                    pass
                time.sleep(1)
        threading.Thread(target=update, daemon=True).start()

    def _stop_grab(self):
        """停止抢购"""
        self.running = False
        self.start_btn.config(state=tk.NORMAL, bg="#fb7299")
        self.stop_btn.config(state=tk.DISABLED, bg="#888")
        self._log("⏹ 抢购已停止", "warning")
        self.countdown_var.set("")

    def _grab_thread(self, act_id, lottery_id, sale_time_str,
                     concurrent, advance, max_retries):
        """抢购线程"""
        try:
            # 解析目标时间
            target = datetime.strptime(sale_time_str, "%Y-%m-%d %H:%M:%S")
            target_ts = target.timestamp()
            fire_ts = target_ts - advance

            # 等待到开售时间
            now_ts = time.time()
            if fire_ts > now_ts:
                wait_sec = fire_ts - now_ts - 1.0
                if wait_sec > 0:
                    self._log(f"  等待 {wait_sec:.0f} 秒后进入忙等待...")
                    time.sleep(wait_sec)
                while time.time() < fire_ts and self.running:
                    pass

            if not self.running:
                return

            self._log("🔥 开售！发起抢购...", "bold")

            # 开始抢购循环
            start_time = time.time()
            success = False
            order_id = ""
            pay_type = self.pay_type.get()

            for attempt in range(1, max_retries + 1):
                if not self.running or success:
                    break

                try:
                    # 构建异步并发请求
                    csrf = self.api.get_csrf_token()

                    async def worker(wid):
                        headers = {
                            "User-Agent": self.api.config.bilibili.user_agent,
                            "Referer": f"https://www.bilibili.com/blackboard/activity-Mz9T5bO5Q3.html?type=dlc&id={act_id}&lottery_id={lottery_id}",
                            "Origin": "https://www.bilibili.com",
                            "Content-Type": "application/x-www-form-urlencoded",
                        }
                        url = f"{self.api.config.bilibili.base_url}/x/garb/trade/create"
                        payloads = [
                            {"item_id": lottery_id, "num": 1, "csrf": csrf, "pay_type": pay_type},
                            {"item_id": act_id, "num": 1, "csrf": csrf, "pay_type": pay_type},
                        ]
                        import httpx
                        async with httpx.AsyncClient(headers=headers, timeout=10) as cl:
                            for ck, cv in self.api._session.cookies.items():
                                cl.cookies.set(ck, cv, domain='.bilibili.com')
                            for payload in payloads:
                                try:
                                    resp = await cl.post(url, data=payload)
                                    data = resp.json()
                                    if data.get("code") == 0:
                                        return data.get("data", {})
                                except:
                                    continue
                        return None

                    tasks = [worker(i) for i in range(concurrent)]
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    results = loop.run_until_complete(
                        asyncio.gather(*tasks, return_exceptions=True))
                    loop.close()

                    for r in results:
                        if isinstance(r, dict) and r:
                            order_id = r.get("order_id", r.get("trade_id", ""))
                            success = True
                            elapsed = time.time() - start_time
                            self._log(f"✓ 第{attempt}次成功！订单号: {order_id}", "success")
                            self._log(f"  耗时: {elapsed:.2f}秒", "success")
                            self._show_success(order_id, attempt, elapsed)
                            return

                    if attempt % 5 == 0:
                        self._log(f"~ 已尝试 {attempt} 次，继续...", "warning")

                    time.sleep(0.5)

                except Exception as e:
                    self._log(f"~ 第{attempt}次出错: {e}", "warning")
                    time.sleep(0.5)

            elapsed = time.time() - start_time
            if not success:
                self._log(f"✗ 抢购失败，已尝试 {max_retries} 次，耗时 {elapsed:.2f}秒", "error")
                self._show_failure(elapsed)

        except Exception as e:
            self._log(f"✗ 抢购异常: {e}", "error")
        finally:
            self.running = False
            self.root.after(0, self._reset_buttons)

    def _reset_buttons(self):
        """重置按钮状态"""
        self.start_btn.config(state=tk.NORMAL, bg="#fb7299")
        self.stop_btn.config(state=tk.DISABLED, bg="#888")
        self.countdown_var.set("")

    def _show_success(self, order_id, attempts, elapsed):
        """显示成功弹窗"""
        self.root.after(0, lambda: messagebox.showinfo(
            "🎉 抢购成功！",
            f"订单号: {order_id}\n"
            f"尝试次数: {attempts}\n"
            f"耗时: {elapsed:.2f}秒\n"
            f"支付方式: {'B币' if self.pay_type.get() == 'bp' else '硬币'}"
        ))

    def _show_failure(self, elapsed):
        """显示失败弹窗"""
        self.root.after(0, lambda: messagebox.showerror(
            "😢 抢购失败",
            f"已用尽所有尝试次数\n耗时: {elapsed:.2f}秒"
        ))


def main():
    root = tk.Tk()
    app = GrabApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
