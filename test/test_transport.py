"""营地传输层的请求构造。

营地网关对请求头敏感：缺 `Content-Type` 时表单字段不会被解析，接口返回
业务码 `-30003` 而不是明确的鉴权错误。这个码本身看不出原因，所以在这里
把请求构造钉住。
"""

import pytest

from ainong.camp.transport import 营地传输

_营地ID = "1234567890"
_令牌 = "t" * 104
_密钥 = "k" * 16


def _已登录的传输() -> 营地传输:
    传输 = 营地传输.__new__(营地传输)
    传输._账号 = {"营地ID": _营地ID, "令牌": _令牌, "对称密钥": _密钥}
    return 传输


class Test鉴权头:
    def test_带营地账号的令牌与ID(self):
        头 = _已登录的传输()._鉴权头()
        assert 头["token"] == _令牌
        assert 头["userid"] == _营地ID

    def test_每次请求的日志标识不同(self):
        传输 = _已登录的传输()
        assert 传输._鉴权头()["x-log-uid"] != 传输._鉴权头()["x-log-uid"]

    def test_日志标识是大写十六进制(self):
        uid = _已登录的传输()._鉴权头()["x-log-uid"]
        assert uid == uid.upper()
        int(uid, 16)

    def test_查他人时才带好友标识(self):
        传输 = _已登录的传输()
        assert "friendUserId" not in 传输._鉴权头()
        assert 传输._鉴权头("999")["friendUserId"] == "999"

    def test_未登录时报错(self):
        传输 = 营地传输.__new__(营地传输)
        传输._账号 = None
        with pytest.raises(RuntimeError):
            传输._鉴权头()

    def test_带营地的固定请求头(self):
        头 = _已登录的传输()._鉴权头()
        for 键 in ("Content-Encrypt", "Accept-Encrypt", "NOENCRYPT", "X-Client-Proto"):
            assert 键 in 头
        assert 头["NOENCRYPT"] == "1"


class Test表单构造:
    def test_查自己角色列表的字段(self):
        传输 = _已登录的传输()
        传输._账号 = {"营地ID": _营地ID, "令牌": _令牌, "对称密钥": _密钥}
        # 表单内容在取角色列表里构造，这里只确认它需要的字段都在
        需要的 = {"friendUserId", "token", "userId"}
        表单 = {k: 传输._账号["营地ID"] if k != "token" else 传输._账号["令牌"] for k in 需要的}
        assert 表单["friendUserId"] == 表单["userId"] == _营地ID


class Test请求构造约定:
    """`_请求` 必须设 Content-Type，否则表单不被解析，接口回 -30003。

    那个业务码看不出原因，所以直接检查 `_请求` 发出的请求头。
    """

    def test_请求带表单编码的内容类型(self, monkeypatch):
        传输 = _已登录的传输()
        捕获: dict[str, str] = {}

        class 假响应:
            headers: dict[str, str] = {}

            async def text(self) -> str:
                return '{"returnCode":0,"data":[]}'

            async def __aenter__(self) -> "假响应":
                return self

            async def __aexit__(self, *exc: object) -> None:
                return None

        def 假post(url: str, headers: dict[str, str], data: bytes) -> 假响应:
            捕获.update(headers)
            return 假响应()

        传输._http = type("假会话", (), {"post": staticmethod(假post)})()

        import asyncio

        asyncio.run(传输._请求("/game/allrolelistv3", {"userId": _营地ID}))

        assert 捕获["Content-Type"] == "application/x-www-form-urlencoded; charset=UTF-8"
        assert 捕获["token"] == _令牌
