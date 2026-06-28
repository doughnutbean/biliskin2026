"""登录管理模块 - Cookie登录、扫码登录、登录态验证"""

import json
import os
import re
import time
from typing import Optional

import requests

from api import BiliAPI, BiliApiError
from config import AppConfig, get_cookies_path


class LoginManager:
    """登录管理器"""

    def __init__(self, api: BiliAPI, config: AppConfig):
        self.api = api
        self.config = config

    # ──────────────── Cookie 登录 ────────────────

    def login_by_cookie(self, cookie_str: str) -> bool:
        """通过Cookie字符串登录
        cookie_str 格式: "key1=value1; key2=value2"
        需要的key: SESSDATA, bili_jct, DedeUserID
        """
        self.api.set_cookies(cookie_str)
        return self._verify_login()

    def login_by_browser(self) -> bool:
        """从浏览器中提取B站Cookie（自动检测常见浏览器）"""
        cookie_str = self._extract_from_browser()
        if not cookie_str:
            print("[!] 未能从浏览器提取到B站Cookie")
            print("[*] 请手动登录后使用 'login cookie' 命令设置")
            return False
        return self.login_by_cookie(cookie_str)

    # ──────────────── 扫码登录 ────────────────

    def _passport_headers(self) -> dict:
        """构建 passport.bilibili.com 接口所需的请求头（避免 412）"""
        return {
            "User-Agent": self.config.bilibili.user_agent,
            "Referer": "https://passport.bilibili.com/login",
            "Origin": "https://passport.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    def _ensure_passport_cookies(self) -> None:
        """确保 session 中有 passport 域所需的基础 Cookie（buvid3/buvid4 等）"""
        if "buvid3" in self.api._session.cookies:
            return  # 已有设备标识 Cookie

        try:
            # 访问 B站首页获取基础 Cookie（buvid3/buvid4/b_nut 等）
            resp = requests.get(
                "https://www.bilibili.com/",
                headers={
                    "User-Agent": self.config.bilibili.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
                timeout=10,
            )
            # 将首页返回的 Cookie 合并到 session
            for cookie in resp.cookies:
                if cookie.name not in self.api._session.cookies:
                    self.api._session.cookies.set(cookie.name, cookie.value)
        except Exception:
            pass  # 获取失败不阻塞，后续请求仍可能成功

    def _get_qrcode_url(self) -> dict:
        """获取扫码登录的二维码信息"""
        self._ensure_passport_cookies()  # 确保有设备指纹 Cookie

        url = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
        resp = requests.get(
            url,
            headers=self._passport_headers(),
            cookies=self.api._session.cookies,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise BiliApiError(f"获取二维码失败: {data.get('message')}")
        return data["data"]

    def _poll_qrcode_status(self, qrcode_key: str) -> dict:
        """轮询扫码登录状态"""
        url = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
        resp = requests.get(
            url,
            params={"qrcode_key": qrcode_key},
            headers=self._passport_headers(),
            cookies=self.api._session.cookies,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def login_by_qrcode(self, status_callback=None) -> bool:
        """扫码登录
        
        Args:
            status_callback: 可选的状态回调 func(msg: str)，用于 GUI 实时反馈
        
        返回: 是否登录成功
        """
        def log(msg):
            if status_callback:
                status_callback(msg)
            else:
                print(msg)

        try:
            import qrcode
            from PIL import Image
        except ImportError:
            log("[!] 扫码登录需要安装依赖: pip install qrcode[pil]")
            log("[*] 请先安装后重试，或使用 'login cookie' 方式登录")
            return False

        # 获取二维码信息
        log("[*] 正在获取登录二维码...")
        qr_data = self._get_qrcode_url()
        qrcode_url = qr_data["url"]
        qrcode_key = qr_data["qrcode_key"]

        # ★ 关键：先把二维码 URL 发给 GUI（必须在可能失败的 print_ascii 之前）
        # 这样 GUI 端可以用自己的 qrcode 库渲染图片，不依赖这里的 console 输出
        if status_callback:
            status_callback(f"__QRCODE_URL__:{qrcode_url}")

        # CLI 模式下显示终端 ASCII 二维码（windowed exe 中 stdout 不可用，加保护）
        log(f"[*] 请使用B站App扫码登录")
        log(f"[*] 二维码链接: {qrcode_url}")
        try:
            qr = qrcode.QRCode(border=2)
            qr.add_data(qrcode_url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        except Exception:
            pass  # 无控制台环境（windowed exe）下 print_ascii 可能失败，忽略

        # 轮询扫码状态
        log("[*] 等待扫码...")
        while True:
            result = self._poll_qrcode_status(qrcode_key)
            # 新版 B站 扫码 API：真实状态码嵌套在 data.code 中
            data = result.get("data", {})
            status_code = data.get("code") if "code" in data else result.get("code")

            if status_code == 0:
                # 扫码确认成功
                url = data.get("url", "")
                refresh_token = data.get("refresh_token", "")
                log(f"[*] 扫码确认！url={url[:100]}...")
                log(f"[*] refresh_token={repr(refresh_token)[:80]}")

                # 方式一：从重定向 URL 提取 Cookie（旧版流程）
                if url:
                    self._extract_cookies_from_url(url, log=log)

                # 方式二：用 refresh_token 换取登录 Cookie（新版流程）
                if refresh_token:
                    log("[*] 使用 refresh_token 换取登录 Cookie...")
                    self._exchange_refresh_token(refresh_token, log=log)

                if self._verify_login(log=log):
                    log("[✓] 扫码登录成功！")
                    self.api.save_cookies()
                    if status_callback:
                        status_callback("__LOGIN_OK__")
                    return True
                else:
                    log("[✗] 扫码后验证登录失败，请重试")
                    return False

            elif status_code == 86038:
                log("[✗] 二维码已失效，请重新生成")
                return False
            elif status_code == 86090:
                log("[*] 已扫码，请在手机上确认登录...")
            elif status_code == 86101:
                pass  # 未扫码，继续等待
            else:
                log(f"[~] 未知状态码 {status_code}: {data.get('message', '')}")

            time.sleep(1.5)

    def _extract_cookies_from_url(self, url: str, log=None) -> None:
        """从重定向URL中提取登录Cookie（手动跟随，捕获每跳 Set-Cookie）"""
        def _log(msg):
            if log: log(msg)
            else: print(msg)
        try:
            _log(f"[*] 正在获取登录 Cookie...")
            _log(f"[*] 目标 URL: {url[:120]}")

            # 收集各域拿到的关键 Cookie（跨域链中域名不同）
            collected = {}

            current_url = url
            for hop in range(5):
                headers = {
                    "User-Agent": self.config.bilibili.user_agent,
                    "Referer": "https://www.bilibili.com/",
                    "Origin": "https://www.bilibili.com",
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                }
                resp = requests.get(
                    current_url,
                    headers=headers,
                    cookies=self.api._session.cookies,
                    allow_redirects=False,
                    timeout=10,
                )
                _log(f"[*] 第{hop+1}跳: {resp.status_code}, Cookie 数: {len(resp.cookies)}, Location: {resp.headers.get('Location', '无')[:80]}")
                for cookie in resp.cookies:
                    if cookie.name in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"):
                        collected[cookie.name] = cookie.value
                        _log(f"[*] 收集 Cookie: {cookie.name} (域: {cookie.domain})")

                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("Location", "")
                    if loc:
                        current_url = loc if loc.startswith("http") else requests.compat.urljoin(current_url, loc)
                        continue
                break

            # ★ 强制写入关键 Cookie 到 session（不指定 domain，使 api.bilibili.com 也能匹配）
            if collected.get("SESSDATA") and collected.get("bili_jct"):
                _log(f"[*] 强制写入关键 Cookie: {list(collected.keys())}")
                for key, val in collected.items():
                    self.api._session.cookies.set(key, val)
        except Exception as e:
            _log(f"[✗] 提取登录Cookie失败: {e}")

    def _exchange_refresh_token(self, refresh_token: str, log=None) -> None:
        """用 refresh_token 换取登录 Cookie（B站新版扫码流程）"""
        def _log(msg):
            if log: log(msg)
            else: print(msg)
        try:
            url = "https://passport.bilibili.com/x/passport-login/web/cookie/info"
            resp = requests.get(
                url,
                params={"refresh_token": refresh_token},
                headers=self._passport_headers(),
                cookies=self.api._session.cookies,
                timeout=10,
            )
            _log(f"[*] token 交换响应: {resp.status_code}, Cookie 数: {len(resp.cookies)}")
            for cookie in resp.cookies:
                self.api._session.cookies.set(cookie.name, cookie.value)
                _log(f"[*] 获得 Cookie: {cookie.name}")
            # 某些情况下 Cookie 在响应体的 JSON 中
            if resp.status_code == 200 and not resp.cookies:
                try:
                    body = resp.json()
                    if body.get("code") == 0 and "data" in body:
                        for key in ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5"]:
                            if key in body["data"]:
                                self.api._session.cookies.set(key, str(body["data"][key]))
                                _log(f"[*] 从 JSON 获得 Cookie: {key}")
                except Exception:
                    pass
        except Exception as e:
            _log(f"[✗] refresh_token 交换失败: {e}")

    # ──────────────── 浏览器Cookie提取 ────────────────

    def _extract_from_browser(self) -> Optional[str]:
        """尝试从浏览器Cookie文件提取B站Cookie"""
        import platform
        system = platform.system()

        # 可能的Cookie路径
        cookie_paths = self._get_browser_cookie_paths(system)

        for path, browser_name in cookie_paths:
            if os.path.exists(path):
                try:
                    cookies = self._parse_chrome_cookies(path)
                    if cookies:
                        print(f"[✓] 从 {browser_name} 提取到B站Cookie")
                        return cookies
                except Exception:
                    continue

        return None

    def _get_browser_cookie_paths(self, system: str) -> list:
        """获取各浏览器的Cookie文件路径"""
        paths = []
        if system == "Windows":
            base = os.environ.get("LOCALAPPDATA", "")
            user_base = os.environ.get("APPDATA", "")
            paths = [
                (os.path.join(base, r"Google\Chrome\User Data\Default\Cookies"), "Chrome"),
                (os.path.join(base, r"Google\Chrome\User Data\Default\Network\Cookies"), "Chrome"),
                (os.path.join(user_base, r"Opera Software\Opera Stable\Network\Cookies"), "Opera"),
                (os.path.join(base, r"Microsoft\Edge\User Data\Default\Network\Cookies"), "Edge"),
                (os.path.join(base, r"BraveSoftware\Brave-Browser\User Data\Default\Network\Cookies"), "Brave"),
                (os.path.join(base, r"Vivaldi\User Data\Default\Network\Cookies"), "Vivaldi"),
            ]
        elif system == "Darwin":
            base = os.path.expanduser("~/Library/Application Support")
            paths = [
                (os.path.join(base, "Google/Chrome/Default/Cookies"), "Chrome"),
                (os.path.join(base, "Microsoft Edge/Default/Cookies"), "Edge"),
                (os.path.join(base, "BraveSoftware/Brave-Browser/Default/Cookies"), "Brave"),
            ]
        else:  # Linux
            base = os.path.expanduser("~/.config")
            paths = [
                (os.path.join(base, "google-chrome/Default/Cookies"), "Chrome"),
                (os.path.join(base, "chromium/Default/Cookies"), "Chromium"),
                (os.path.join(base, "microsoft-edge/Default/Cookies"), "Edge"),
                (os.path.join(base, "brave-browser/Default/Cookies"), "Brave"),
            ]
        return paths

    def _parse_chrome_cookies(self, cookie_path: str) -> Optional[str]:
        """解析Chrome系浏览器的Cookie文件，提取B站Cookie"""
        try:
            import sqlite3
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            import platform
            import base64

            conn = sqlite3.connect(cookie_path)
            cursor = conn.cursor()

            # 查询B站相关的Cookie
            cursor.execute(
                "SELECT name, encrypted_value, host_key FROM cookies "
                "WHERE host_key LIKE '%bilibili.com%' "
                "AND name IN ('SESSDATA', 'bili_jct', 'DedeUserID', 'DedeUserID__ckMd5')"
            )
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                return None

            # 尝试解密
            # Chrome >= 80 使用AESGCM加密
            key = self._get_chrome_encryption_key()
            cookies_dict = {}
            for name, enc_value, host in rows:
                if not enc_value:
                    continue
                value = self._decrypt_chrome_cookie(enc_value, key)
                if value:
                    cookies_dict[name] = value

            if "SESSDATA" in cookies_dict and "bili_jct" in cookies_dict:
                parts = []
                for key in ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"]:
                    if key in cookies_dict:
                        parts.append(f"{key}={cookies_dict[key]}")
                    # 尝试从cookie文件的其他地方获取缺失的key
                    if key not in cookies_dict:
                        # 尝试从文件重新查询
                        try:
                            conn2 = sqlite3.connect(cookie_path)
                            c2 = conn2.cursor()
                            c2.execute(
                                "SELECT name, value FROM cookies WHERE host_key LIKE '%bilibili.com%' AND name=?",
                                (key,)
                            )
                            r2 = c2.fetchone()
                            conn2.close()
                            if r2 and r2[1]:
                                parts.append(f"{r2[0]}={r2[1]}")
                        except:
                            pass
                return "; ".join(parts) if parts else None

            return None

        except ImportError:
            print("[!] 浏览器Cookie解密需要安装: pip install cryptography")
            return None
        except Exception as e:
            print(f"[警告] 解析Cookie失败: {e}")
            return None

    def _get_chrome_encryption_key(self) -> Optional[bytes]:
        """获取Chrome本地加密密钥"""
        import platform
        system = platform.system()
        if system == "Windows":
            try:
                import win32crypt
            except ImportError:
                return None
            # Windows上Chrome使用DPAPI加密的key存储
            local_state_path = self._get_local_state_path()
            if not local_state_path:
                return None
            try:
                with open(local_state_path, "r", encoding="utf-8") as f:
                    local_state = json.load(f)
                encrypted_key = base64.b64decode(local_state.get("os_crypt", {}).get("encrypted_key", ""))
                # 去除前5个字节的"DPAPI"头
                encrypted_key = encrypted_key[5:]
                key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
                return key
            except Exception:
                return None
        elif system in ("Darwin", "Linux"):
            # macOS/Linux的Chrome使用keychain/gnome-keyring
            # 简化处理：从Local State读取
            local_state_path = self._get_local_state_path()
            if not local_state_path:
                return None
            try:
                with open(local_state_path, "r", encoding="utf-8") as f:
                    local_state = json.load(f)
                key_b64 = local_state.get("os_crypt", {}).get("encrypted_key", "")
                if not key_b64:
                    # 旧版Chrome可能没有加密
                    return b"peanuts"
                encrypted_key = base64.b64decode(key_b64)
                encrypted_key = encrypted_key[5:]  # remove "DPAPI"
                return encrypted_key  # 在macOS上这已经是解密后的
            except Exception:
                return None
        return None

    def _get_local_state_path(self) -> Optional[str]:
        """获取Chrome Local State文件路径"""
        import platform
        system = platform.system()
        if system == "Windows":
            base = os.environ.get("LOCALAPPDATA", "")
            return os.path.join(base, r"Google\Chrome\User Data\Local State")
        elif system == "Darwin":
            return os.path.expanduser("~/Library/Application Support/Google/Chrome/Local State")
        else:
            for path in [
                os.path.expanduser("~/.config/google-chrome/Local State"),
                os.path.expanduser("~/.config/chromium/Local State"),
            ]:
                if os.path.exists(path):
                    return path
            return None

    def _decrypt_chrome_cookie(self, encrypted_data: bytes, key: Optional[bytes]) -> Optional[str]:
        """解密Chrome Cookie值"""
        if not key or not encrypted_data:
            return None

        try:
            # Chrome >= 80 格式: v10 + nonce(12字节) + ciphertext + tag(16字节)
            if encrypted_data[:3] == b"v10" or encrypted_data[:3] == b"v11":
                nonce = encrypted_data[3:15]
                ciphertext = encrypted_data[15:]
                try:
                    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                    aesgcm = AESGCM(key)
                    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
                    return plaintext.decode("utf-8")
                except Exception:
                    return None
            else:
                # 旧版Chrome使用DPAPI
                try:
                    import win32crypt
                    decrypted, _ = win32crypt.CryptUnprotectData(encrypted_data, None, None, None, 0)
                    return decrypted.decode("utf-8")
                except ImportError:
                    # 对于macOS/Linux上的旧版
                    return encrypted_data.decode("utf-8", errors="ignore")
        except Exception:
            return None

    # ──────────────── 工具方法 ────────────────

    def _verify_login(self, log=None) -> bool:
        """验证当前登录状态"""
        def _log(msg):
            if log: log(msg)
            else: print(msg)
        try:
            data = self.api.check_login()
            if data.get("isLogin"):
                uname = data.get("uname", "")
                mid = data.get("mid", 0)
                _log(f"[✓] 登录成功！用户: {uname} (UID: {mid})")
                return True
            else:
                _log("[✗] 未登录，Cookie无效或已过期")
                return False
        except BiliApiError as e:
            _log(f"[✗] 登录验证失败: {e}")
            return False

    def is_logged_in(self) -> bool:
        """简单检查是否已登录（不输出日志）"""
        try:
            data = self.api.check_login()
            return data.get("isLogin", False)
        except Exception:
            return False

    def get_current_user(self) -> Optional[str]:
        """获取当前登录用户名"""
        try:
            data = self.api.check_login()
            if data.get("isLogin"):
                return f"{data.get('uname', '')} (UID: {data.get('mid', 0)})"
        except Exception:
            pass
        return None

    # ──────────────── 一键登录 ────────────────

    def _extract_with_browser_cookie3(self, status_callback=None) -> Optional[str]:
        """使用 browser_cookie3 库从浏览器自动提取 B站 Cookie
        
        Args:
            status_callback: 可选的状态回调
        
        Returns:
            Cookie 字符串，失败返回 None
        """
        def log(msg):
            if status_callback:
                status_callback(msg)
            else:
                print(msg)

        try:
            import browser_cookie3
        except ImportError:
            log("[!] browser-cookie3 未安装，跳过浏览器提取")
            log("[*] 安装命令: pip install browser-cookie3")
            return None

        needed_keys = {"SESSDATA", "bili_jct", "DedeUserID"}
        browsers = [
            ("Chrome",  lambda: browser_cookie3.chrome(domain_name="bilibili.com")),
            ("Edge",    lambda: browser_cookie3.edge(domain_name="bilibili.com")),
            ("Firefox", lambda: browser_cookie3.firefox(domain_name="bilibili.com")),
            ("Brave",   lambda: browser_cookie3.brave(domain_name="bilibili.com")),
            ("Opera",   lambda: browser_cookie3.opera(domain_name="bilibili.com")),
        ]

        for browser_name, loader in browsers:
            try:
                log(f"[*] 尝试从 {browser_name} 提取...")
                cj = loader()
                cookies = {}
                for cookie in cj:
                    if cookie.name in needed_keys or cookie.name == "DedeUserID__ckMd5" or cookie.name == "sid":
                        cookies[cookie.name] = cookie.value

                if "SESSDATA" in cookies and "bili_jct" in cookies:
                    parts = []
                    for key in ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid"]:
                        if key in cookies:
                            parts.append(f"{key}={cookies[key]}")
                    result = "; ".join(parts)
                    log(f"[✓] 从 {browser_name} 提取成功")
                    return result
            except Exception:
                # browser_cookie3 在浏览器锁库、权限不足等情况下会抛异常
                continue

        return None

    def login_quick(self, status_callback=None) -> tuple:
        """一键登录：优先从浏览器提取 Cookie，失败则扫码登录
        
        Args:
            status_callback: 可选的状态回调 func(msg: str)
        
        Returns:
            (success: bool, method: str) — 是否成功 + 登录方式描述
        """
        def log(msg):
            if status_callback:
                status_callback(msg)
            else:
                print(msg)

        # 第一步：尝试从浏览器自动提取
        log("[*] 一键登录：正在从浏览器提取 B站 Cookie...")
        try:
            cookie_str = self._extract_with_browser_cookie3(status_callback=status_callback)
            if cookie_str:
                if self.login_by_cookie(cookie_str):
                    log("[✓] 从浏览器提取 Cookie 成功！")
                    return (True, "浏览器自动提取")
        except Exception as e:
            log(f"[~] 浏览器提取异常: {e}")

        log("[*] 浏览器提取失败，切换为扫码登录...")

        # 第二步：扫码登录（加 try/except 防止异常静默吞掉）
        try:
            if self.login_by_qrcode(status_callback=status_callback):
                return (True, "扫码登录")
        except Exception as e:
            log(f"[✗] 扫码登录异常: {e}")

        log("[✗] 登录失败")
        return (False, "登录失败")
