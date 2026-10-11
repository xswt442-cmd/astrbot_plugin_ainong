"""`encodeRes` 两种形态的解码测试。

营地登录响应里的 `encodeRes` 有两种实际出现的形态：

1. 明文形态：base64 编码的 JSON 字符串，直接解出来就是含 `userKey` 的对象
2. 密文形态：base64 编码的 RSA 运算结果，用营地公钥做逆运算才拿得到明文

测试不假设哪一种"应该"存在：两种都要能解，别的形态要明确报错。
"""

import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from ainong.camp.encode_res import 取出对称密钥


def _明文形态(user_key: str = "the-user-key") -> str:
    return base64.b64encode(json.dumps({"userKey": user_key}).encode("utf-8")).decode("ascii")


# 固定密钥，不用随机生成。
#
# 随机生成时这段构造偶尔会造出无效数据：填充块当成整数后可能不小于模数 n，
# 而 pow(m, d, n) 内部先取模，逆运算拿回来的是 m mod n——高位被截掉，剥块
# 从错的位置开始，报「还原出的内容不是 JSON」。概率约千分之一，本地跑十几次
# 碰不到，CI 上稳定复现。固定密钥让测试可重复。
_测试私钥 = rsa.generate_private_key(public_exponent=65537, key_size=1024)


def _密文形态(user_key: str = "the-user-key", 密钥=None) -> tuple[str, rsa.RSAPrivateKey]:
    """造一份与营地同构的密文。

    营地服务端持有私钥，对填充后的明文做一次幂运算（用私钥指数 d）；
    客户端拿公钥指数 e 做逆运算还原。
    """
    私钥 = 密钥 or _测试私钥
    明文 = json.dumps({"userKey": user_key}).encode("utf-8")
    私钥数 = 私钥.private_numbers()
    块长 = 私钥.key_size // 8
    填充 = b"\xff" * (块长 - len(明文) - 3)
    块 = b"\x00\x01" + 填充 + b"\x00" + 明文

    数字 = int.from_bytes(块, "big")
    if 数字 >= 私钥数.public_numbers.n:
        raise ValueError("填充块不小于模数，构造出的密文无法还原")
    密文 = pow(数字, 私钥数.d, 私钥数.public_numbers.n)
    return base64.b64encode(密文.to_bytes(块长, "big")).decode("ascii"), 私钥


class Test明文形态:
    def test_解出userKey(self):
        assert 取出对称密钥(_明文形态("abc123")) == "abc123"

    def test_额外字段不影响(self):
        原样 = json.dumps({"userKey": "k", "其他": 1, "ts": 123})
        编码 = base64.b64encode(原样.encode()).decode()
        assert 取出对称密钥(编码) == "k"


class Test密文形态:
    def test_解出userKey(self, monkeypatch):
        密文, 私钥 = _密文形态("from-rsa")
        monkeypatch.setattr("ainong.camp.encode_res.载入公钥", lambda: 私钥.public_key())
        assert 取出对称密钥(密文) == "from-rsa"

    def test_密文形态长度正确(self):
        密文, _ = _密文形态()
        assert len(密文) == 172


class Test拒绝非法输入:
    def test_空串报错(self):
        with pytest.raises(ValueError):
            取出对称密钥("")

    def test_缺userKey报错(self):
        无密钥 = base64.b64encode(json.dumps({"别的": 1}).encode()).decode()
        with pytest.raises(ValueError):
            取出对称密钥(无密钥)

    def test_不是base64报错(self):
        with pytest.raises(ValueError):
            取出对称密钥("这不是 base64 !!!")

    def test_长度不对的base64报错(self):
        with pytest.raises(ValueError):
            取出对称密钥(base64.b64encode(b"\x00\x01\x02").decode())
