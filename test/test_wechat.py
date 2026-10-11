"""微信扫码出码与轮询的测试。

微信扫码与 QQ 扫码是两套机制：微信出码走官方 HTTP 接口直接返回图片，
全程不需要浏览器；QQ 要开真实授权页截取页面元素。二者只有最后的营地
登录共用部分逻辑。

签名串的拼接顺序与 query 参数的顺序不同，这是对的，不要统一。
"""

import hashlib
import time

import pytest

from ainong.auth.wechat import (
    WECHAT_APPID,
    build_poll_query,
    build_qr_query,
    build_qr_sign_text,
    sign,
    检测图片类型,
    解析出码响应,
    解析扫码状态,
)


class TestSign:
    def test_与独立计算一致(self):
        text = build_qr_sign_text("appid=x", "12345678", "TICKET", "1700000000")
        expected = hashlib.sha1(text.encode("utf-8")).hexdigest()
        assert sign(text) == expected

    def test_是小写十六进制(self):
        摘要 = sign("whatever")
        assert 摘要 == 摘要.lower()
        assert len(摘要) == 40

    def test_不是base64(self):
        # base64 会含 + / = 这类字符，hex 不会
        for i in range(20):
            摘要 = sign(f"value-{i}")
            assert not set(摘要) & set("+/=")

    def test_内容不同则签名不同(self):
        assert sign("a") != sign("b")


class TestSignTextOrder:
    def test_票据在时间戳之前(self):
        text = build_qr_sign_text("A", "12345678", "TICK", "999")
        assert text == "appid=A&noncestr=12345678&sdk_ticket=TICK&timestamp=999"

    def test_字段顺序固定(self):
        text = build_qr_sign_text("A", "N", "T", "S")
        位置 = [text.index(k) for k in ("appid=", "noncestr=", "sdk_ticket=", "timestamp=")]
        assert 位置 == sorted(位置)


class TestQrQuery:
    def test_包含五个参数(self):
        查询 = build_qr_query("TICKET", str(int(time.time())))
        assert set(查询) == {"appid", "noncestr", "timestamp", "scope", "signature"}

    def test_appid固定(self):
        查询 = build_qr_query("TICKET", "1")
        assert 查询["appid"] == WECHAT_APPID
        assert 查询["appid"] == "wxf4b1e8a3e9aaf978"

    def test_范围是用户信息(self):
        查询 = build_qr_query("TICKET", "1")
        assert 查询["scope"] == "snsapi_userinfo"

    def test_随机串是八位数字(self):
        for _ in range(10):
            查询 = build_qr_query("TICKET", "1")
            assert len(查询["noncestr"]) == 8
            assert 查询["noncestr"].isdigit()

    def test_签名对应当前参数(self):
        查询 = build_qr_query("TICKET", "1700000000")
        assert 查询["signature"] == sign(
            build_qr_sign_text(查询["appid"], 查询["noncestr"], "TICKET", 查询["timestamp"])
        )

    def test_签名与票据绑定(self):
        甲 = build_qr_query("TICKET-A", "1700000000")
        乙 = build_qr_query("TICKET-B", "1700000000")
        assert 甲["signature"] != 乙["signature"]

    def test_时间戳默认取当前秒(self):
        查询 = build_qr_query("TICKET")
        assert int(查询["timestamp"]) <= int(time.time()) + 2


class TestPollQuery:
    def test_包含格式与uuid(self):
        查询 = build_poll_query("UUID-1234")
        assert 查询 == {"f": "json", "uuid": "UUID-1234"}


class Test扫码状态:
    def test_已确认时返回授权码(self):
        状态 = 解析扫码状态({"errcode": 0, "wx_errcode": 405, "wx_code": "THE-CODE"})
        assert 状态["状态"] == "已确认"
        assert 状态["授权码"] == "THE-CODE"

    def test_已确认但无授权码算异常(self):
        状态 = 解析扫码状态({"errcode": 0, "wx_errcode": 405})
        assert 状态["状态"] == "异常"
        assert 状态["终态"] is False

    def test_已扫码待确认(self):
        状态 = 解析扫码状态({"errcode": 0, "wx_errcode": 404})
        assert 状态["状态"] == "已扫码"
        assert 状态["终态"] is False

    def test_等待扫码(self):
        状态 = 解析扫码状态({"errcode": 0, "wx_errcode": 408})
        assert 状态["状态"] == "等待"
        assert 状态["终态"] is False

    def test_过期是终态(self):
        状态 = 解析扫码状态({"errcode": 0, "wx_errcode": 402})
        assert 状态["状态"] == "过期"
        assert 状态["终态"] is True

    def test_取消是终态(self):
        状态 = 解析扫码状态({"errcode": 0, "wx_errcode": 403})
        assert 状态["状态"] == "已取消"
        assert 状态["终态"] is True

    def test_未知状态码不是终态(self):
        状态 = 解析扫码状态({"errcode": 0, "wx_errcode": 500})
        assert 状态["状态"] == "异常"
        assert 状态["终态"] is False

    def test_缺状态码时不是终态(self):
        状态 = 解析扫码状态({})
        assert 状态["状态"] == "异常"
        assert 状态["终态"] is False

    def test_状态码是字符串时也能解析(self):
        状态 = 解析扫码状态({"errcode": 0, "wx_errcode": "405", "wx_code": "X"})
        assert 状态["状态"] == "已确认"


class TestQrPayload:
    def test_取出二维码与uuid(self):
        图片 = base64_b64(b"\x89PNG\r\n\x1a\n")
        结果 = 解析出码响应({"errcode": 0, "uuid": "U-1", "qrcode": {"qrcodebase64": 图片}})
        assert 结果["uuid"] == "U-1"
        assert 结果["二维码"] == 图片

    def test_微信返回的是jpeg(self):
        图片 = base64_b64(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
        assert (
            解析出码响应({"errcode": 0, "uuid": "U", "qrcode": {"qrcodebase64": 图片}})["图片类型"]
            == "image/jpeg"
        )

    def test_jpeg魔数识别为jpeg(self):
        assert 检测图片类型(base64_b64(b"\xff\xd8\xff")) == "image/jpeg"

    def test_png魔数识别为png(self):
        assert 检测图片类型(base64_b64(b"\x89PNG\r\n\x1a\n")) == "image/png"

    def test_gif魔数识别为gif(self):
        assert 检测图片类型(base64_b64(b"GIF89a")) == "image/gif"

    def test_webp魔数识别为webp(self):
        assert 检测图片类型(base64_b64(b"RIFF\x00\x00\x00\x00WEBP")) == "image/webp"

    def test_未知魔数兜底为jpeg(self):
        assert 检测图片类型(base64_b64(b"garbage")) == "image/jpeg"

    def test_缺二维码时报错(self):
        with pytest.raises(RuntimeError):
            解析出码响应({"errcode": 0, "uuid": "U", "qrcode": {}})

    def test_缺uuid时报错(self):
        with pytest.raises(RuntimeError):
            解析出码响应({"errcode": 0, "qrcode": {"qrcodebase64": "AAAA"}})

    def test_出码失败时报错(self):
        with pytest.raises(RuntimeError):
            解析出码响应({"errcode": 40029, "errmsg": "invalid"})


def base64_b64(原始: bytes) -> str:
    import base64 as b64

    return b64.b64encode(原始).decode("ascii")


class TestAppId:
    def test_是公开的微信AppId(self):
        # 这是营地公开客户端的 AppID，不是 AppSecret
        assert WECHAT_APPID == "wxf4b1e8a3e9aaf978"


@pytest.mark.parametrize("次数", [1, 2, 3])
def test_随机串不重复(次数):
    查询 = build_qr_query("TICKET", "1")
    assert 查询["noncestr"] != "12345678"
