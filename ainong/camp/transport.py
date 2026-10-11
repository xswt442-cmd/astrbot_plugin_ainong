"""营地接口的传输层。

负责拼请求头、加解密参数与响应、处理响应业务码。不含业务语义。
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from typing import Any

import aiohttp

from ..crypto.pkcs1 import strip_pkcs1_padding
from ..crypto.xxtea import decrypt as xxtea_decrypt
from ..crypto.xxtea import encrypt as xxtea_encrypt
from ..crypto.xxtea import normalize_key
from .pacing import 频控闸

__all__ = ["营地传输"]

营地主站 = "https://kohcamp.qq.com"
营地网关 = "https://ssl.kohsocialapp.qq.com:10001"

营地内置公钥 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC0h62mV/zjJtFsNdfFNlxksfUOpjDI2KCcBrPiA8T7"
    "szABT4InLDTrdXAW84QyGNiazB0i7pgPCNGSAYbiJrCRutZ5jQsVS0Wg/RnXfwVQDJcAHJDjP5IXyroe"
    "LX7NUxDai8nPcpfRsvq6sneobyPexZSH0TlVSnecsJZTj5wu/wIDAQAB"
)

_客户端头 = {
    "cChannelId": "10003391",
    "cClientVersionCode": "2057971306",
    "cClientVersionName": "10.114.0826",
    "cCurrentGameId": "20001",
    "cGameId": "20001",
    "cGzip": "1",
    "cIsArm64": "true",
    "cSupportArm64": "true",
    "cSystem": "android",
    "cSystemVersionCode": "35",
    "cSystemVersionName": "15",
    "cpuHardware": "qcom",
    "gameId": "20001",
    "tinkerId": "2057971306_64_0",
}

# 微信路径的客户端参数。营地区分两个来源，版本号不能与 QQ 路径混用。
_微信客户端头 = {
    **_客户端头,
    "cClientVersionCode": "2057957801",
    "cClientVersionName": "10.111.0323",
    "cSystemVersionCode": "34",
    "cSystemVersionName": "14",
    "tinkerId": "2057957801_64_0",
}

_公共头 = {
    "Content-Encrypt": "",
    "Accept-Encrypt": "",
    "NOENCRYPT": "1",
    "X-Client-Proto": "https",
    "User-Agent": "okhttp/4.9.1",
}

_营地网关 = "https://ssl.kohsocialapp.qq.com:10001"
营地网关 = _营地网关

# 营地返回的业务码
_玩家已隐藏 = -10107
_账号频控 = -30107

_业务错误文案 = {
    _玩家已隐藏: "该玩家在王者营地关闭了战绩展示，请让对方在营地的隐私设置里打开",
    _账号频控: "这个营地账号被限流了，冷却中",
}


class 业务错误(Exception):
    """营地接口返回了失败的业务码。"""


# 冷却信息跨请求存在，账号维度的限流不能按传输实例算——每次查询都新建实例。
全局频控 = 频控闸()


class 营地传输:
    """营地接口的 HTTP 客户端。每个登录会话持有一个。"""

    def __init__(self) -> None:
        self._http = aiohttp.ClientSession()
        self._账号: dict[str, str] | None = None

    async def 关闭(self) -> None:
        await self._http.close()

    async def __aenter__(self) -> 营地传输:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.关闭()

    def 绑定账号(self, 营地ID: str, 令牌: str, 对称密钥: str) -> None:
        self._账号 = {"营地ID": 营地ID, "令牌": 令牌, "对称密钥": 对称密钥}

    def _闸(self):
        """取当前账号的频控闸。冷却信息在账号维度，不在传输实例上。"""
        if self._账号 is None:
            raise RuntimeError("尚未登录营地账号")
        return 全局频控.取账号闸(self._账号["营地ID"])

    async def _等闸放行(self) -> None:
        """等到可以发请求为止。冷却期长到无法等待时直接报错。"""
        import asyncio

        闸 = self._闸()
        if 闸.冷却中():
            raise 业务错误(闸.可读提示())
        等待 = 闸.还需等待()
        if 等待 > 0:
            await asyncio.sleep(等待)
        闸.记录发出()

    def _鉴权头(self, 目标营地ID: str | None = None) -> dict[str, str]:
        if self._账号 is None:
            raise RuntimeError("尚未登录营地账号")
        头 = dict(_公共头)
        头["x-log-uid"] = secrets.token_hex(16).upper()
        头["token"] = self._账号["令牌"]
        头["userid"] = self._账号["营地ID"]
        if 目标营地ID is not None:
            头["friendUserId"] = 目标营地ID
        return 头

    def _加签(self, 明文: dict[str, Any]) -> str:
        """构造请求参数加密串。"""
        assert self._账号 is not None
        紧凑 = json.dumps(明文, separators=(",", ":"))
        密钥 = normalize_key(self._账号["对称密钥"].encode("utf-8"))
        return base64.b64encode(xxtea_encrypt(紧凑.encode("utf-8"), 密钥)).decode("ascii")

    def _解密响应(self, 文本: str, 响应头: Any) -> str:
        """响应头标记加密时才解密。"""
        if 响应头.get("campencrypt") != "true":
            return 文本
        assert self._账号 is not None
        密钥 = normalize_key(self._账号["对称密钥"].encode("utf-8"))
        return xxtea_decrypt(base64.b64decode(文本), 密钥).decode("utf-8")

    async def _请求(
        self,
        路径: str,
        表单: dict[str, str],
        目标营地ID: str | None = None,
        主机: str = 营地网关,
    ) -> dict[str, Any]:
        import urllib.parse

        头 = self._鉴权头(目标营地ID)
        头["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"

        await self._等闸放行()

        异步上下文 = self._http.post(
            f"{主机}{路径}",
            headers=头,
            data=urllib.parse.urlencode(表单),
        )
        async with 异步上下文 as 响应:
            文本 = await 响应.text()
            解密后 = self._解密响应(文本, 响应.headers)

        try:
            载荷 = json.loads(解密后)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"营地响应不是 JSON：{解密后[:200]}") from exc

        self._检查业务码(载荷)
        return 载荷

    def _检查业务码(self, 载荷: dict[str, Any]) -> None:
        码 = 载荷.get("returnCode", 0)
        if 码 == 0:
            return
        if 码 == _账号频控 and self._账号 is not None:
            全局频控.取账号闸(self._账号["营地ID"]).记频控()
        文案 = _业务错误文案.get(码)
        if 文案 is None:
            文案 = f"营地返回业务码 {码}"
        raise 业务错误(文案)

    async def 登录(
        self,
        *,
        平台凭据: dict[str, str] | None = None,
        微信授权码: str | None = None,
        日志标识: str | None = None,
    ) -> dict[str, str]:
        """登录营地，返回营地账号信息。

        两条路径的客户端版本号不同，出码方式也不同：QQ 走 YSDK 换票，
        微信走官方扫码。营地按这两个值区分来源，不能混用。
        """
        import uuid

        from .device import 构建设备载荷
        from .rsa import 分块加密

        if (平台凭据 is None) == (微信授权码 is None):
            raise ValueError("必须提供平台凭据或微信授权码，且只能提供其中一个")

        if 微信授权码 is not None:
            客户端头 = dict(_微信客户端头)
            登录类型 = "wx"
            鉴权字段 = {"code": 微信授权码}
        else:
            客户端头 = dict(_客户端头)
            登录类型 = "openSdk"
            鉴权字段 = {
                "accessToken": 平台凭据["accessToken"],
                "openId": 平台凭据["openId"],
                "payToken": 平台凭据.get("payToken", ""),
            }

        设备载荷 = json.dumps(构建设备载荷(), separators=(",", ":"))
        随机数 = str(int(time.time() * 1000))
        加密载荷 = base64.b64encode(分块加密(设备载荷.encode("utf-8"))).decode("ascii")

        表单 = {
            **客户端头,
            "cRand": 随机数,
            "delOldUser": "0",
            "key1": secrets.token_hex(16),
            "lastLoginTime": "0",
            "lastGetRemarkTime": "0",
            "specialEncodeParam": 加密载荷,
            "loginType": 登录类型,
            **鉴权字段,
        }

        头 = dict(_公共头)
        头["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        头["x-log-uid"] = 日志标识 or str(uuid.uuid4()).upper()
        头.update(客户端头)
        头["cRand"] = 随机数
        头["specialEncodeParam"] = 加密载荷

        import urllib.parse

        async with self._http.post(
            f"{营地网关}/user/login",
            headers=头,
            data=urllib.parse.urlencode(表单),
        ) as 响应:
            载荷 = json.loads(await 响应.text())

        self._检查业务码(载荷)
        数据 = 载荷.get("data") or {}
        if not 数据.get("userId") or not 数据.get("token"):
            raise RuntimeError("营地登录响应里没有账号信息")

        from .encode_res import 取出对称密钥

        密钥 = 取出对称密钥(str(数据["encodeRes"]))
        账号 = {
            "营地ID": str(数据["userId"]),
            "令牌": str(数据["token"]),
            "对称密钥": 密钥,
        }
        self.绑定账号(**账号)
        return 账号

    async def 取角色列表(self) -> list[dict[str, str]]:
        """当前账号下的游戏角色列表。"""
        assert self._账号 is not None
        表单 = {
            "friendUserId": self._账号["营地ID"],
            "token": self._账号["令牌"],
            "userId": self._账号["营地ID"],
        }
        载荷 = await self._请求("/game/allrolelistv3", 表单)
        角色 = 载荷.get("data") or []
        return [
            {
                "角色ID": str(项.get("roleId", "")),
                "名称": str(项.get("roleName", "")),
                "区服描述": str(项.get("roleDesc", "")),
            }
            for 项 in 角色
        ]


def 还原块(密文: bytes) -> bytes:
    """剥掉 PKCS#1 v1.5 块结构。"""
    return strip_pkcs1_padding(密文)
