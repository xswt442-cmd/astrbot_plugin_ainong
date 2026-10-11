"""YSDK 签名构造的测试。

QQ 授权码换取平台凭据时，请求体与请求头里的签名必须逐字节对应：
签名串是 `POST\n/cmd/QQCodeLogin\njson\nysdk\n{时间戳}\n{请求体}`，
用 HMAC-SHA256 签，密钥为 `yyb@cloud_game:CQ8FA#`。
"""

import base64
import hashlib
import hmac
import json

from ainong.auth.ysdk import YSDK_SIGN_KEY, build_auth_headers, build_sign_text, sign


class TestBuildSignText:
    def test_六段用换行连接且顺序固定(self):
        text = build_sign_text("1700000000", '{"appID":"1105200115","loginCode":"abc"}')
        assert text == (
            "POST\n/cmd/QQCodeLogin\njson\nysdk\n1700000000\n"
            '{"appID":"1105200115","loginCode":"abc"}'
        )

    def test_请求体原样出现在末尾(self):
        body = '{"a":"b"}'
        assert build_sign_text("1", body).endswith("\n" + body)


class TestSign:
    def test_与独立计算一致(self):
        text = build_sign_text("1700000000", '{"appID":"x"}')
        expected = base64.b64encode(
            hmac.new(YSDK_SIGN_KEY, text.encode("utf-8"), hashlib.sha256).digest()
        ).decode("ascii")
        assert sign(text) == expected

    def test_输出是合法base64(self):
        base64.b64decode(sign("whatever").encode("ascii"))

    def test_签名随内容变化(self):
        assert sign("a") != sign("b")

    def test_密钥是规定的字节串(self):
        assert YSDK_SIGN_KEY == b"yyb@cloud_game:CQ8FA#"


class TestBuildAuthHeaders:
    def test_包含三个必需头(self):
        body = json.dumps({"appID": "1105200115", "loginCode": "abc"}, separators=(",", ":"))
        headers = build_auth_headers(body, "1700000000")
        assert headers["Content-Type"] == "json"
        assert headers["Auth-Secret-ID"] == "ysdk"
        assert headers["Auth-Request-Time"] == "1700000000"

    def test_摘要与请求体对应(self):
        body = '{"appID":"x"}'
        headers = build_auth_headers(body, "1700000000")
        assert headers["Auth-Secret-Digest"] == sign(build_sign_text("1700000000", body))

    def test_请求体改变则摘要改变(self):
        a = build_auth_headers('{"loginCode":"a"}', "1")["Auth-Secret-Digest"]
        b = build_auth_headers('{"loginCode":"b"}', "1")["Auth-Secret-Digest"]
        assert a != b


class TestCompactJsonBody:
    def test_请求体不含多余空格(self):
        body = json.dumps({"appID": "1105200115", "loginCode": "abc"}, separators=(",", ":"))
        assert " " not in body

    def test_键顺序保持插入顺序(self):
        body = json.dumps({"appID": "1", "loginCode": "2"}, separators=(",", ":"))
        assert body == '{"appID":"1","loginCode":"2"}'
