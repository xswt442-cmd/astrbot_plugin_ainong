"""QQ 扫码登录的最小可行性验证。

分五步，每步打印结果，任何一步失败立即停止并说明失败在哪：
1. 打开授权页
2. 截取二维码并持续刷新
3. 等待扫码，直到捕获授权码
4. 用授权码换取平台凭据（纯 HTTP）
5. 用平台凭据登录营地，取出营地账号与游戏角色

二维码在人工扫码期间会过期（QQ 侧约两分钟），所以第 2 步起定时刷新，
重新打开授权页取一张新的。扫到哪张算哪张。

浏览器通过 `PLAYWRIGHT_SERVER` 指定，默认 `http://127.0.0.1:3000`。
第 4、5 步不走浏览器。

用法：
    PLAYWRIGHT_SERVER=http://127.0.0.1:3000 uv run python -m ainong.verify.qq_login
"""

from __future__ import annotations

import json
import os
import sys

from ..auth.browser import 浏览器会话
from ..auth.qq_login import QQ_LOGIN_URL, QQ_USER_AGENT, 换取平台凭据
from ..camp.transport import 营地传输
from .qr_server import 启动, 开浏览器

扫码超时秒 = int(os.environ.get("SCAN_TIMEOUT", "600"))
二维码刷新秒 = int(os.environ.get("QR_REFRESH", "25"))
轮询间隔秒 = 1


def 步骤(序号: int, 标题: str) -> None:
    print(f"\n{'=' * 60}\n步骤 {序号}：{标题}\n{'=' * 60}", flush=True)


async def 刷新二维码直到扫码(会话: 浏览器会话, 二维码路径: str) -> str:
    """反复重开授权页取新图，直到捕获授权码。

    二维码从生成到失效只有约两分钟，人工拿到图再扫要用掉大半，所以不等它失效，
    主动换新。
    """
    import asyncio
    import time

    截止 = time.monotonic() + 扫码超时秒
    第几张 = 0
    while time.monotonic() < 截止:
        第几张 += 1
        print(f"取第 {第几张} 张二维码…", flush=True)
        try:
            await 会话.换页重开(QQ_LOGIN_URL)
            图片 = await 会话.取二维码()
        except Exception as exc:
            print(f"  取图失败：{exc}，{二维码刷新秒} 秒后重试", flush=True)
            await asyncio.sleep(二维码刷新秒)
            continue

        剩余 = int(截止 - time.monotonic())
        print(
            f"  已保存 {二维码路径}（{len(图片)} 字节），剩余可扫时间 {剩余} 秒",
            flush=True,
        )

        等待到 = min(二维码刷新秒, 剩余)
        片段结束 = time.monotonic() + 等待到
        while time.monotonic() < 片段结束:
            if 会话.已获授权码:
                return 会话.已获授权码
            await asyncio.sleep(轮询间隔秒)

    raise TimeoutError(f"{扫码超时秒} 秒内没有等到扫码完成")


def 保存凭据(平台凭据: dict[str, str], 路径: str) -> None:
    """把平台凭据落盘。

    accessToken 有效期 60 天，落盘后后续排查不必重新扫码。
    """
    with open(路径, "w", encoding="utf-8") as f:
        json.dump(平台凭据, f)
    try:
        os.chmod(路径, 0o600)
    except OSError:
        pass
    print(f"凭据已保存到 {路径}（内容不打印）", flush=True)


async def main() -> int:
    服务地址 = os.environ.get("PLAYWRIGHT_SERVER", "http://127.0.0.1:3000")
    二维码路径 = os.environ.get("QR_PATH") or os.path.join(
        os.environ.get("TMP", "."), "ainong_qq_qr.png"
    )
    凭据路径 = os.environ.get("CREDENTIALS_PATH") or os.path.join(
        os.environ.get("TMP", "."), "ainong_qq_credentials.json"
    )
    扫码页端口 = int(os.environ.get("QR_SERVER_PORT", "8765"))

    扫码服务, 扫码页地址 = 启动(二维码路径, 扫码页端口)

    print(f"Playwright 服务：{服务地址}", flush=True)
    print(f"扫码页面：{扫码页地址}", flush=True)
    print(f"凭据保存到：{凭据路径}", flush=True)
    print(f"每 {二维码刷新秒} 秒换一张新图，直到扫到或超过 {扫码超时秒} 秒", flush=True)

    步骤(1, "启动浏览器并打开授权页")
    async with 浏览器会话(服务地址, QQ_USER_AGENT, 二维码路径) as 会话:
        await 会话.打开(QQ_LOGIN_URL)
        print("授权页已打开", flush=True)

        步骤(2, "取二维码（持续刷新）")
        开浏览器(扫码页地址)
        code = await 刷新二维码直到扫码(会话, 二维码路径)
        print(f"\n已捕获授权码，长度 {len(code)}", flush=True)

    扫码服务.shutdown()
    平台凭据 = await 换取平台凭据(code)
    保存凭据(平台凭据, 凭据路径)

    步骤(5, "登录营地并取账号信息")
    async with 营地传输() as 传输:
        账号 = await 传输.登录(平台凭据=平台凭据)
        print(f"营地账号 ID：{账号['营地ID']}", flush=True)
        print(f"令牌长度：{len(账号['令牌'])}", flush=True)
        print(f"对称密钥长度：{len(账号['对称密钥'])}", flush=True)

        角色列表 = await 传输.取角色列表()
        print(f"该账号下的游戏角色数：{len(角色列表)}", flush=True)
        for 角色 in 角色列表:
            print(f"  - {角色['名称']}（{角色['区服描述']}）角色 ID={角色['角色ID']}", flush=True)

    print(f"\n{'=' * 60}")
    print("最小可行性验证通过：QQ 扫码 → 平台凭据 → 营地账号 → 角色列表")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    import asyncio

    try:
        sys.exit(asyncio.run(main()))
    except TimeoutError:
        print("\n验证失败：扫码超时。", flush=True)
        sys.exit(1)
    except Exception as exc:
        print(f"\n验证失败：{type(exc).__name__}: {exc}", flush=True)
        sys.exit(1)
