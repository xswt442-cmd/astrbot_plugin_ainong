"""爱农：王者营地战绩查询。

用户绑定自己的营地账号后，指令与模型都能读到他自己的战绩数据。
"""

from __future__ import annotations

from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.event.filter import command, llm_tool
from astrbot.api.star import Context, Star

from .ainong.camp.transport import 营地传输
from .ainong.storage import 凭据仓库

绑定超时秒 = 180


class Main(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self._凭据 = 凭据仓库(self._数据目录())
        self._扫码会话: dict[str, _扫码] = {}

    def _数据目录(self) -> Path:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path

        return Path(get_astrbot_data_path()) / "plugin_data" / "ainong"

    async def terminate(self) -> None:
        for 会话 in list(self._扫码会话.values()):
            await 会话.关闭()
        self._扫码会话.clear()

    # ---------------------------------------------------------------- 绑定

    @command("绑定")
    async def 绑定(self, event: AstrMessageEvent):
        """扫码绑定王者营地账号。"""
        用户 = event.get_sender_id()
        if not 用户:
            yield event.plain_result("拿不到你的用户标识，无法绑定。")
            return

        已有 = self._凭据.读取(用户)
        if 已有:
            yield event.plain_result(f"你已经绑定了营地账号 {已有['营地ID']}。要换号先用 /解绑。")
            return

        if 用户 in self._扫码会话:
            yield event.plain_result("扫码已经在进行中，看上一条消息里的二维码。")
            return

        会话 = _扫码(用户, self.config)
        self._扫码会话[用户] = 会话
        try:
            图片 = await 会话.出码()
        except Exception as exc:
            self._扫码会话.pop(用户, None)
            yield event.plain_result(f"取二维码失败：{exc}")
            return

        from astrbot.api.message_components import Image

        yield event.chain_result([Image.fromBase64(图片), f"扫码绑定，{绑定超时秒} 秒内有效。"])

    @command("解绑")
    async def 解绑(self, event: AstrMessageEvent):
        """解除绑定并删除凭据。"""
        用户 = event.get_sender_id()
        会话 = self._扫码会话.pop(用户, None)
        if 会话 is not None:
            await 会话.关闭()

        记录 = self._凭据.删除(用户)
        if not 记录:
            yield event.plain_result("你还没有绑定营地账号。")
            return
        yield event.plain_result(f"已解绑，凭据已删除（营地账号 {记录['营地ID']}）。")

    # ---------------------------------------------------------------- 查询

    @command("角色")
    async def 角色(self, event: AstrMessageEvent):
        """列出该营地账号下的游戏角色。"""
        用户 = event.get_sender_id()
        记录 = self._凭据.读取(用户)
        if not 记录:
            yield event.plain_result("还没绑定营地账号，先发 /绑定。")
            return

        async with 营地传输() as 传输:
            传输.绑定账号(**{k: 记录[k] for k in ("营地ID", "令牌", "对称密钥")})
            列表 = await 传输.取角色列表()

        if not 列表:
            yield event.plain_result("这个营地账号下没有游戏角色。")
            return

        当前 = self._凭据.当前角色(用户)
        行 = [
            f"{'（当前）' if 角色['角色ID'] == 当前 else ''}{角色['名称']}"
            f"｜{角色['区服描述']}｜{角色['角色ID']}"
            for 角色 in 列表
        ]
        yield event.plain_result("游戏角色：\n" + "\n".join(行))

    @command("战绩")
    async def 战绩(self, event: AstrMessageEvent):
        """当前角色的近期战绩摘要。"""
        文本 = await self._读战绩(event.get_sender_id())
        yield event.plain_result(文本)

    @llm_tool(name="get_king_of_glory_profile")
    async def 查询玩家画像(self, event: AstrMessageEvent) -> str:
        """读取提问者自己绑定的王者荣耀账号战绩，并给出结构化摘要。

        Returns:
            段位、常用英雄与位置、近期胜率与评分等统计结果。玩家关闭了
            战绩展示时返回说明文字。
        """
        return await self._读战绩(event.get_sender_id())

    async def _读战绩(self, 用户: str) -> str:
        记录 = self._凭据.读取(用户)
        if not 记录:
            return "提问者还没有绑定王者营地账号，无法查询战绩。"

        from .ainong.camp.battles import 读战绩摘要

        async with 营地传输() as 传输:
            传输.绑定账号(**{k: 记录[k] for k in ("营地ID", "令牌", "对称密钥")})
            try:
                return await 读战绩摘要(传输, 记录.get("角色ID") or "")
            except Exception as exc:
                logger.warning(f"[ainong] 读战绩失败：{type(exc).__name__}: {exc}")
                return f"读取战绩失败：{exc}"


class _扫码:
    """一次扫码绑定会话。"""

    def __init__(self, 用户: str, config: AstrBotConfig) -> None:
        self.用户 = 用户
        self._浏览器地址 = str(config.get("browser_server_url", "") or "")
        self._超时 = int(config.get("browser_timeout_seconds", 120) or 120)

    async def 出码(self) -> str:
        """出二维码并等待扫码完成，返回 base64 图片。"""
        if not self._浏览器地址:
            raise RuntimeError("未配置浏览器服务，无法扫码")

        from .ainong.auth.wechat import 扫码出码

        return await 扫码出码(self._浏览器地址, self._超时)

    async def 关闭(self) -> None:
        return
