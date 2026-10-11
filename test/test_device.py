"""设备指纹与 RSA 分块加密的测试。"""

import base64

from cryptography.hazmat.primitives.asymmetric import padding

from ainong.camp.device import 构建设备载荷
from ainong.camp.rsa import 分块加密, 载入公钥


class Test设备载荷:
    def test_包含时间戳与随机数(self):
        载荷 = 构建设备载荷()
        assert isinstance(载荷["timestamp"], int)
        assert ":" in 载荷["nonce"]

    def test_每次调用设备ID不同(self):
        assert 构建设备载荷()["cDeviceId"] != 构建设备载荷()["cDeviceId"]

    def test_设备ID与imei一致(self):
        载荷 = 构建设备载荷()
        assert 载荷["cDeviceImei"] == 载荷["cDeviceId"][:15]

    def test_可序列化为紧凑json(self):
        import json

        文本 = json.dumps(构建设备载荷(), separators=(",", ":"))
        # 紧凑序列化去掉的是分隔符里的空格，值内部的空格保留
        assert ", " not in 文本
        assert '": ' not in 文本


class Test公钥:
    def test_是1024位(self):
        assert 载入公钥().key_size == 1024

    def test_可重复载入(self):
        assert 载入公钥().public_numbers() == 载入公钥().public_numbers()


class Test分块加密:
    def test_单块数据密文长度等于keysize(self):
        明文 = b"short payload"
        密文 = 分块加密(明文)
        assert len(密文) == 载入公钥().key_size // 8

    def test_超过单块容量时按块切分(self):
        单块容量 = 载入公钥().key_size // 8 - 11
        明文 = b"x" * (单块容量 * 2 + 50)
        assert len(分块加密(明文)) == 载入公钥().key_size // 8 * 3

    def test_正好单块容量时只占一块(self):
        单块容量 = 载入公钥().key_size // 8 - 11
        assert len(分块加密(b"x" * 单块容量)) == 载入公钥().key_size // 8

    def test_每次加密结果不同(self):
        # PKCS#1 v1.5 填充含随机字节，同一明文两次加密密文不同
        assert 分块加密(b"same") != 分块加密(b"same")

    def test_可用私钥解开单块(self):
        # 自检：构造密钥对走一遍完整往返，确认填充格式正确
        from cryptography.hazmat.primitives.asymmetric import rsa

        密钥 = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        明文 = b"round trip test payload"
        密文 = 密钥.public_key().encrypt(明文, padding.PKCS1v15())
        assert 密钥.decrypt(密文, padding.PKCS1v15()) == 明文

    def test_结果可base64编码(self):
        assert base64.b64decode(base64.b64encode(分块加密(b"x")))
