"""B站API封装模块 - 所有B站接口调用集中管理"""

import json
import re
import time
from typing import Optional
from urllib.parse import urlencode

import httpx
import requests

from config import AppConfig, get_cookies_path


class BiliApiError(Exception):
    """B站API调用异常"""
    pass


_time_offset = 0.0  # 服务器时间 - 本地时间 偏差（秒）

def sync_server_time(resp_headers: dict) -> None:
    """从响应头同步服务器时间"""
    global _time_offset
    date_str = resp_headers.get("date", "")
    if date_str:
        from datetime import datetime
        try:
            server_dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %Z")
            import time
            server_ts = server_dt.timestamp()
            local_ts = time.time()
            _time_offset = server_ts - local_ts
        except ValueError:
            pass


def get_server_timestamp() -> float:
    """获取B站服务器当前时间戳（通过本地时间+偏差计算）"""
    import time
    return time.time() + _time_offset


class BiliAPI:
    """B站API客户端"""

    def __init__(self, config: AppConfig):
        self.config = config
        self._session = requests.Session()
        self._async_client: Optional[httpx.AsyncClient] = None

        # 设置请求头
        headers = {
            "User-Agent": config.bilibili.user_agent,
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        # 代理设置
        proxies = None
        if config.proxy.enabled:
            proxies = {
                "http": config.proxy.http,
                "https": config.proxy.https,
            } if config.proxy.http or config.proxy.https else None

        self._session.headers.update(headers)
        if proxies:
            self._session.proxies.update(proxies)

        # 加载Cookie
        self._load_cookies()

    def _load_cookies(self) -> None:
        """从文件加载Cookie"""
        try:
            with open(get_cookies_path(), "r", encoding="utf-8") as f:
                cookies = json.load(f)
            for key, value in cookies.items():
                self._session.cookies.set(key, value)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def save_cookies(self) -> None:
        """将当前Session中的Cookie保存到文件"""
        cookies = {
            key: value
            for key, value in self._session.cookies.items()
            if key in ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "sid")
        }
        with open(get_cookies_path(), "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

    def set_cookies(self, cookies_str: str) -> None:
        """从字符串设置Cookie（格式: key1=value1; key2=value2）"""
        for part in cookies_str.split(";"):
            part = part.strip()
            if "=" in part:
                key, value = part.split("=", 1)
                self._session.cookies.set(key.strip(), value.strip())
        self.save_cookies()

    def get_cookies_string(self) -> str:
        """获取当前Cookie字符串"""
        return "; ".join(
            f"{k}={v}" for k, v in self._session.cookies.items()
        )

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
        json_data: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> dict:
        """通用请求方法"""
        url = f"{self.config.bilibili.base_url}{path}"
        req_headers = headers or {}
        req_headers.setdefault("User-Agent", self.config.bilibili.user_agent)

        try:
            resp = self._session.request(
                method=method,
                url=url,
                params=params,
                data=data,
                json=json_data,
                headers=req_headers,
                timeout=10,
            )
            resp.raise_for_status()
            result = resp.json()
            # 同步服务器时间
            sync_server_time(resp.headers)
            # 设置代理为None，绕过系统HTTP_PROXY环境变量，直连B站
            proxies = {"http": None, "https": None}
        except requests.exceptions.Timeout:
            raise BiliApiError(f"请求超时: {method} {path}")
        except requests.exceptions.RequestException as e:
            raise BiliApiError(f"请求失败: {method} {path} - {e}")
        except json.JSONDecodeError:
            raise BiliApiError(f"响应不是有效JSON: {resp.text[:200]}")

        # B站API通用错误码处理
        code = result.get("code", -1)
        if code != 0:
            msg = result.get("message", result.get("msg", "未知错误"))
            if code == -101:
                raise BiliApiError("未登录或Cookie失效，请重新登录")
            elif code == -111:
                raise BiliApiError("CSRF token验证失败")
            elif code == 22007:
                raise BiliApiError("库存不足或已售罄")
            raise BiliApiError(f"API错误(code={code}): {msg}")

        return result.get("data", result)

    def _request_direct(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
        json_data: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> dict:
        """带直接模式的请求（绕过系统代理）"""
        url = f"{self.config.bilibili.base_url}{path}"
        req_headers = headers or {}
        req_headers.setdefault("User-Agent", self.config.bilibili.user_agent)

        try:
            resp = self._session.request(
                method=method,
                url=url,
                params=params,
                data=data,
                json=json_data,
                headers=req_headers,
                timeout=10,
                proxies={"http": None, "https": None},
            )
            resp.raise_for_status()
            result = resp.json()
            sync_server_time(resp.headers)
        except requests.exceptions.Timeout:
            raise BiliApiError(f"请求超时: {method} {path}")
        except requests.exceptions.RequestException as e:
            raise BiliApiError(f"请求失败: {method} {path} - {e}")
        except json.JSONDecodeError:
            raise BiliApiError(f"响应不是有效JSON: {resp.text[:200]}")

        code = result.get("code", -1)
        if code != 0:
            msg = result.get("message", result.get("msg", "未知错误"))
            if code == -101:
                raise BiliApiError("未登录或Cookie失效，请重新登录")
    # ──────────────── 登录态相关 ────────────────

    def check_login(self) -> dict:
        """检查登录状态
        返回: {"isLogin": bool, "uname": str, "mid": int, ...}
        """
        return self._request("GET", "/x/web-interface/nav")

    def get_user_info(self) -> dict:
        """获取用户信息"""
        data = self._request("GET", "/x/web-interface/nav")
        return data

    def get_csrf_token(self) -> str:
        """从Cookie中提取bili_jct作为csrf token"""
        return self._session.cookies.get("bili_jct", "")

    # ──────────────── 装扮相关 ────────────────

    def get_suit_detail(self, item_id: int) -> dict:
        """获取装扮详情
        GET /x/garb/v2/mall/suit/detail?item_id={item_id}
        """
        return self._request(
            "GET",
            "/x/garb/v2/mall/suit/detail",
            params={"item_id": item_id},
        )

    def get_suit_stock(self, item_ids: list) -> dict:
        """获取装扮库存
        GET /x/garb/mall/item/suit?item_id={id}
        """
        ids_str = ",".join(str(i) for i in item_ids)
        return self._request(
            "GET",
            "/x/garb/mall/item/suit",
            params={"item_ids": ids_str},
        )

    def get_suit_list(self, page: int = 1, page_size: int = 20) -> dict:
        """获取装扮列表（在售装扮）
        GET /x/garb/v2/mall/suit/list?page={page}&page_size={page_size}
        """
        return self._request(
            "GET",
            "/x/garb/mall/list",
            params={"page": page, "page_size": page_size},
        )

    def search_suit(self, keyword: str, page: int = 1) -> dict:
        """搜索装扮
        GET /x/garb/v2/mall/suit/search?keyword={keyword}&page={page}
        """
        return self._request(
            "GET",
            "/x/garb/mall/list",
            params={"keyword": keyword, "page": page},
        )

    def create_order(
        self,
        item_id: int,
        num: int = 1,
        suit_id: int = 0,
        pay_type: str = "bp",
    ) -> dict:
        """创建订单（下单购买）
        POST /x/garb/trade/create
        pay_type: bp=B币支付, coin=硬币支付
        需要csrf
        """
        csrf = self.get_csrf_token()
        data = {
            "item_id": item_id,
            "num": num,
            "csrf": csrf,
            "pay_type": pay_type,
        }
        if suit_id:
            data["suit_id"] = suit_id
        return self._request(
            "POST",
            "/x/garb/trade/create",
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://www.bilibili.com/",
                "Origin": "https://www.bilibili.com",
            },
        )

    def get_order_status(self, order_id: str) -> dict:
        """查询订单状态
        GET /x/garb/trade/query?order_id={order_id}
        """
        return self._request(
            "GET",
            "/x/garb/trade/query",
            params={"order_id": order_id},
        )

    def get_account_info(self) -> dict:
        """获取账户信息（B币余额等）
        GET /x/web-interface/nav 获取用户信息
        GET /x/garb/user/asset 获取资产信息(含B币余额)
        """
        user = self._request("GET", "/x/web-interface/nav")
        try:
            asset = self._request("GET", "/x/garb/user/asset")
            if isinstance(asset, dict):
                user["asset"] = asset
        except BiliApiError:
            pass
        return user

    def get_my_orders(self, page: int = 1, page_size: int = 10) -> dict:
        """获取我的订单列表
        GET /x/garb/trade/query?page={page}&page_size={page_size}
        """
        return self._request(
            "GET",
            "/x/garb/trade/query",
            params={"page": page, "page_size": page_size},
        )

    # ──────────────── 数字卡片/抽奖相关 ────────────────

    def get_kuji_box_items(self, lottery_id: int) -> dict:
        """获取抽奖盒子物品列表
        GET /x/garb/kuji/boxitem/all?lottery_id={lottery_id}
        """
        return self._request(
            "GET",
            "/x/garb/kuji/boxitem/all",
            params={"lottery_id": lottery_id},
        )

    def create_kuji_order(
        self,
        lottery_id: int,
        num: int = 1,
    ) -> dict:
        """创建抽奖订单
        POST /x/garb/kuji/trade/create
        """
        csrf = self.get_csrf_token()
        return self._request(
            "POST",
            "/x/garb/kuji/trade/create",
            data={
                "lottery_id": lottery_id,
                "num": num,
                "csrf": csrf,
            },
        )

    def query_kuji_trade(self, trade_id: str = "", page: int = 1) -> dict:
        """查询抽奖交易
        GET /x/garb/kuji/trade/query
        """
        params = {"page": page}
        if trade_id:
            params["trade_id"] = trade_id
        return self._request(
            "GET",
            "/x/garb/kuji/trade/query",
            params=params,
        )

    def get_mall_tabs(self) -> dict:
        """获取装扮商城分类
        GET /x/garb/mall/tabs
        """
        return self._request("GET", "/x/garb/mall/tabs")

    # ──────────────── 异步支持 ────────────────

    async def _async_request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
        json_data: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> dict:
        """异步通用请求（用于高并发抢购）"""
        url = f"{self.config.bilibili.base_url}{path}"
        req_headers = headers or {}
        req_headers.setdefault("User-Agent", self.config.bilibili.user_agent)
        req_headers.setdefault("Referer", "https://www.bilibili.com/")
        req_headers.setdefault("Origin", "https://www.bilibili.com")

        # 从同步session获取cookie字符串传给异步客户端
        cookie_str = self.get_cookies_string()

        if self._async_client is None:
            proxies = None
            if self.config.proxy.enabled:
                proxies = self.config.proxy.https or self.config.proxy.http
            self._async_client = httpx.AsyncClient(
                headers=req_headers,
                cookies=httpx.Cookies(),
                proxies=proxies,
                timeout=10,
                follow_redirects=True,
            )

        # 设置cookie
        for key, value in self._session.cookies.items():
            self._async_client.cookies.set(key, value)

        try:
            if method.upper() == "GET":
                resp = await self._async_client.request(
                    method, url, params=params
                )
            else:
                resp = await self._async_client.request(
                    method, url, params=params, data=data, json=json_data
                )
            resp.raise_for_status()
            result = resp.json()
        except httpx.TimeoutException:
            raise BiliApiError(f"异步请求超时: {method} {path}")
        except httpx.HTTPError as e:
            raise BiliApiError(f"异步请求失败: {method} {path} - {e}")
        except json.JSONDecodeError:
            raise BiliApiError(f"异步响应不是有效JSON")

        code = result.get("code", -1)
        if code != 0:
            msg = result.get("message", result.get("msg", "未知错误"))
            raise BiliApiError(f"API错误(code={code}): {msg}")

        return result.get("data", result)

    async def async_create_order(
        self,
        item_id: int,
        num: int = 1,
        from_type: str = "mall",
    ) -> dict:
        """异步创建订单"""
        csrf = self.get_csrf_token()
        return await self._async_request(
            "POST",
            "/x/garb/mall/trade/create-order",
            data={
                "item_id": item_id,
                "num": num,
                "from_type": from_type,
                "csrf": csrf,
            },
        )

    async def async_get_suit_stock(self, item_ids: list) -> dict:
        """异步获取库存"""
        ids_str = ",".join(str(i) for i in item_ids)
        return await self._async_request(
            "GET",
            "/x/garb/mall/v2/suit/stock",
            params={"item_ids": ids_str},
        )

    async def close_async_client(self) -> None:
        """关闭异步客户端"""
        if self._async_client:
            await self._async_client.aclose()
            self._async_client = None