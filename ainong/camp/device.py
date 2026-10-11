"""营地登录用的设备指纹。

这些字段描述一台 Android 设备。营地用它做风控判定，不是账号凭据。
"""

from __future__ import annotations

import secrets
import time
from typing import Any

__all__ = ["构建设备载荷"]


def 构建设备载荷() -> dict[str, Any]:
    """构造一次登录用的设备指纹。

    设备 ID 每次登录新生成：营地不要求同一台设备的 ID 稳定，而复用同一个
    ID 会让多个用户的请求在营地侧看起来来自同一台设备。
    """
    时间戳 = int(time.time() * 1000)
    设备ID = secrets.token_hex(16)
    return {
        "timestamp": 时间戳,
        "nonce": f":{secrets.token_hex(16)}:{时间戳}",
        "cDeviceId": 设备ID,
        "deviceid": 设备ID,
        "cDeviceImei": 设备ID[:15],
        "cDeviceMac": "02:00:00:00:00:00",
        "cDeviceType": "NAN-TG8",
        "cDeviceBrand": "Xiaomi",
        "cDeviceModel": "Xiaomi 13",
        "cDeviceSystem": "Android 15,level 35",
        "cDeviceLanguage": "zh_CN",
        "cDeviceCountry": "CN",
        "cScreenResolution": "1080*2400",
        "cNetworkType": "wifi",
        "cDeviceChannel": "10003391",
        "cDeviceVersionName": "10.114.0826",
    }
