"""爱农：王者营地战绩查询。

用户绑定自己的营地账号后，指令与模型都能读到他自己的战绩数据。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.event.filter import command_group, llm_tool
from astrbot.api.star import Context, Star
from astrbot.core.message.message_event_result import MessageEventResult
from astrbot.core.star.filter.command import GreedyStr

# 全部在模块顶层导入。插件加载时就把整个包摸清：少文件、依赖缺失都在启动
# 阶段报错，而不是等用户发了指令才在懒加载里抛模块不存在。
from .ainong.auth.qq_login import QQ扫码会话, 换取平台凭据
from .ainong.auth.scan_session import 扫码会话
from .ainong.camp.battles import 读战绩数据
from .ainong.camp.transport import 营地传输
from .ainong.pk import 找对手
from .ainong.prompts import PK提示, 开一局提示, 锐评提示
from .ainong.stats import 占优项数, 对比文本, 对比要点, 抽对局结果
from .ainong.storage import 凭据仓库

_帮助文本 = """爱农 · 王者营地战绩

/爱农 绑定微信
  微信扫码绑定你自己的营地账号。纯 HTTP，不需要浏览器。

/爱农 绑定QQ
  手机 QQ 扫码绑定。码两分钟就过期，我会在过期前发新的，以最后一张为准。
  需要浏览器侧车（在服务器上单独跑着 Chromium）。

/爱农 角色 [角色ID]
  不带参数：列出这个营地账号下的游戏角色，标出当前选中的。
  带角色ID：切换到该角色，之后的查询都看它。

/爱农 战绩
  当前角色的近期战绩：段位与星数、巅峰分、胜率、KDA、MVP 占比、SVP、
  奖牌、一血与超神、局内评价、模式分布、英雄池、最近 10 场走势与连胜连败。

/爱农 锐评
  让模型基于上面的数据写一段锐评。会先给一句称号，再分别说打得好、
  问题和一条具体建议。

/爱农 PK <名字>
  和另一个人比近期战绩。写对方的 PK 名字，例如 /爱农 PK 老王。
  也可以直接给对方的用户标识。双方都得先绑定营地账号。
  模型会给两人各打一个趣味分并点评胜负手。

/爱农 昵称 <名字>
  给自己起一个 PK 用的名字，群友才能用 /爱农 PK <名字> 点你。
  不带参数则看当前的名字。

/爱农 开一局
  假设他又开了一局排位，让模型推演这一局的过程与结果。
  胜负按他自己的胜率抽，不是每次都能赢。

/爱农 解绑
  解除绑定并立即删除本地凭据。扫码卡住时也可以用它清掉当前会话。

/爱农 状态
  看自己的标识、绑定情况和有没有卡住的扫码会话。排查用。

/爱农 帮助
  就是这条。

直接问模型「我的王者战绩怎么样」也会走同一套数据。"""

_PK用法 = """要跟谁 PK？写对方的 PK 名字就行，例如：
/爱农 PK 老王

不知道对方的名字？让对方发一次 /爱农 昵称 <名字> 给自己起一个，
或者把他的用户标识发过来（发 /爱农 状态 能看到自己的）。

对方必须先绑定过营地账号。@ 对方这条路在 QQ 官方平台走不通——平台
不把被 @ 的人的标识交给机器人，事件里连痕迹都没有。"""

# PK 名字的长度上限。只是个称呼，太长在比分那行会挤爆。
_昵称上限 = 16


class Main(Star):
    @command_group("爱农")
    def 爱农(self):
        """王者营地战绩查询。指令都在这个组下，不占用通用名字。"""

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self._凭据 = 凭据仓库(self._数据目录())
        # 两种授权的会话都放这儿：微信的纯 HTTP，QQ 的要浏览器。用基线类型标注，
        # 两者都实现出码/开始等待/关闭。
        self._扫码会话: dict[str, 扫码会话 | QQ扫码会话] = {}
        # 留着原始事件，扫码完成后用它回复。QQ 官方 bot 的主动消息要群授权、
        # 每条还消耗额度（日志里是「主动消息失败, 无权限」），而带 msg_id 的
        # 被动回复不需要。两者用时不同，所以事件和会话标识都留着。
        self._事件: dict[str, AstrMessageEvent] = {}
        self._会话标识: dict[str, str] = {}

    def _数据目录(self) -> Path:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path

        return Path(get_astrbot_data_path()) / "plugin_data" / "ainong"

    def _扫码超时(self) -> int:
        return int(self.config.get("browser_timeout_seconds", 180) or 180)

    async def terminate(self) -> None:
        for 会话 in list(self._扫码会话.values()):
            await 会话.关闭()
        self._扫码会话.clear()
        self._事件.clear()
        self._会话标识.clear()

    # ---------------------------------------------------------------- 绑定

    @爱农.command("帮助", alias={"help", "菜单"})
    async def 帮助(self, event: AstrMessageEvent):
        """列出所有指令。"""
        yield event.plain_result(_帮助文本)

    @爱农.command("绑定微信", alias={"绑定"})
    async def 绑定微信(self, event: AstrMessageEvent):
        """扫码绑定王者营地账号，走微信授权。"""
        async for 结果 in self._绑定(event, 平台="微信"):
            yield 结果

    @爱农.command("绑定QQ", alias={"绑定qq"})
    async def 绑定QQ(self, event: AstrMessageEvent):
        """扫码绑定王者营地账号，走 QQ 授权。需要浏览器侧车。"""
        async for 结果 in self._绑定(event, 平台="QQ"):
            yield 结果

    async def _绑定(self, event: AstrMessageEvent, 平台: str):
        """两种授权的公共流程。差异只在出码与等待，各自在下面分支。"""
        用户 = event.get_sender_id()
        if not 用户:
            yield event.plain_result("拿不到你的用户标识，无法绑定。")
            return

        已有 = self._凭据.读取(用户)
        if 已有:
            yield event.plain_result(
                f"你已经绑定了营地账号 {已有['营地ID']}。要换号先用 /爱农 解绑。"
            )
            return

        if 用户 in self._扫码会话:
            yield event.plain_result(
                f"{平台}扫码已经在进行中，看上一条消息里的二维码。"
                "如果那张码已经失效，发 /爱农 解绑 清掉当前会话后重试。"
            )
            return

        # 两种回话方式要用的东西不一样：event 走被动回复（带 msg_id，不需要
        # 主动消息权限），会话标识走主动消息兜底。
        self._事件[用户] = event
        self._会话标识[用户] = event.unified_msg_origin

        if 平台 == "QQ":
            会话 = QQ扫码会话(self._侧车地址(), self._扫码超时())
            try:
                图片 = await 会话.出码()
            except Exception as exc:
                await 会话.关闭()
                await self._清理会话(用户, None)
                yield event.plain_result(f"QQ 扫码启动失败：{exc}")
                return

            self._扫码会话[用户] = 会话
            提示 = (
                "用手机 QQ 扫这个码。这张码很快会过期，我会在过期前发新的，"
                "以最后一张为准。\n扫完我自动回你结果，没反应就发 /爱农 状态。"
            )
        else:
            会话 = 扫码会话(self._扫码超时())
            try:
                图片 = await 会话.出码()
            except Exception as exc:
                await 会话.关闭()
                await self._清理会话(用户, None)
                yield event.plain_result(f"取二维码失败：{exc}")
                return

            self._扫码会话[用户] = 会话
            提示 = (
                "用微信扫这个码，扫完等一会儿。\n"
                "扫完我会自动回你结果；如果一直没反应，发 /爱农 状态 查一下。"
            )

        # `_完成` 是本函数的局部函数，不是方法——写 `self._完成` 会 AttributeError
        # （v0.1.8 线上原话）。它炸在扫码成功之后，用户看到的是「扫完了却报错」。
        async def _完成(平台凭据: dict[str, str] | str) -> None:
            await self._收到授权码(用户, 平台凭据)

        if 平台 == "QQ":

            async def _完成QQ(code: str) -> None:
                # 换票必须 await：`换取平台凭据` 是协程函数，不 await 就把一个
                # 从未被 await 的协程对象当凭据传下去。
                await _完成(await 换取平台凭据(code))

            会话.开始等待(_完成QQ, self._换码通知(用户), self._扫码失败(用户, 平台))
        else:
            会话.开始等待(_完成, self._扫码失败(用户, 平台))

        # 用链式接口而不是 event.chain_result([...])：后者要的是消息组件列表，
        # 塞裸字符串进去，发送前的日志环节会 AttributeError 崩掉整条流水线，
        # 用户那边只看到没反应。组件由这里的接口负责转换。
        yield event.plain_result(提示).base64_image(图片)

    def _侧车地址(self) -> str:
        """浏览器侧车的地址。QQ 扫码要靠它，微信那条不需要。"""
        return str(self.config.get("playwright_url", "") or "http://playwright:3000")

    def _昵称(self, 用户: str) -> str:
        """发起绑定那个人的平台显示名。取不到就空着，不猜。"""
        事件 = self._事件.get(用户)
        if 事件 is None:
            return ""
        try:
            return str(事件.get_sender_name() or "")
        except Exception:
            return ""

    def _换码通知(self, 用户: str) -> Callable[[str], Any]:
        """二维码换了就再推一张。QQ 的码两分钟就过期，用户手上那张会废掉。"""

        async def _通知(图片: str) -> None:
            await self._通知图片(用户, 图片, "刚才那张码过期了，用这张新的。")

        return _通知

    def _扫码失败(self, 用户: str, 平台: str = "") -> Callable[[BaseException], Any]:
        """后台等待出问题时清场并告知用户。

        原来这类异常只是让 task 静默崩掉：不清理 _扫码会话，用户再发绑定
        只会一直看到"扫码已经在进行中"，而他其实什么都没在扫。
        """

        async def _处理(exc: BaseException) -> None:
            if isinstance(exc, asyncio.CancelledError):
                raise exc
            logger.warning(f"[ainong] 扫码等待失败：{type(exc).__name__}: {exc}")
            # 先通知再清理：_通知 依赖 _事件 与 _会话标识，清理会把它们丢掉。
            await self._通知(用户, f"{平台}扫码没走完：{exc}\n发 /爱农 状态 可以随时查进度。")
            await self._清理会话(用户, 会话=self._扫码会话.pop(用户, None))

        return _处理

    async def _收到授权码(self, 用户: str, 授权: dict[str, str] | str) -> None:
        """扫码完成后登录营地并存凭据。

        `授权` 有两种形态：微信给的是授权码字符串，走 `微信授权码` 参数；
        QQ 那条已经换好了平台凭据，走 `平台凭据`。营地按这两条路径用不同的
        客户端版本号，不能混——传错会被服务端拒。
        """
        会话 = self._扫码会话.pop(用户, None)
        if 会话 is None:
            return

        try:
            传输 = 营地传输()
            try:
                if isinstance(授权, str):
                    账号 = await 传输.登录(微信授权码=授权)
                else:
                    账号 = await 传输.登录(平台凭据=授权)
            finally:
                await 传输.关闭()

            # 顺手记下平台显示名。PK 时要念出双方的名字，而对手的显示名只能
            # 在对方绑定时留下——事件在 PK 那一刻是拿不到的。
            昵称 = self._昵称(用户)
            self._凭据.写入(用户, {**账号, "昵称": 昵称})
            logger.info(f"[ainong] 用户绑定营地账号 {账号['营地ID']}")
            # 顺便把 PK 名字报出来：平台给的是 QQ 昵称而不是群昵称，不提示的话
            # 没人知道该去改。
            await self._通知(
                用户,
                f"绑定成功，营地账号 {账号['营地ID']}。发 /爱农 战绩 试试。\n"
                f"PK 用的名字是「{昵称 or '（这次没取到）'}」，"
                "想换就发 /爱农 昵称 <名字>。",
            )
        except Exception as exc:
            logger.warning(f"[ainong] 绑定失败：{type(exc).__name__}: {exc}")
            await self._通知(用户, f"绑定失败：{exc}")
        finally:
            await self._清理会话(用户, 会话)

    async def _清理会话(self, 用户: str, 会话: 扫码会话 | QQ扫码会话 | None) -> None:
        """关掉会话、丢掉事件与会话标识。

        三样都要丢。事件持有平台侧的上下文，留着既可能让通知发到上一轮的
        会话里去，也长期占着平台对象不放。
        """
        self._事件.pop(用户, None)
        self._会话标识.pop(用户, None)
        if 会话 is not None:
            await 会话.关闭()

    async def _通知(self, 用户: str, 文本: str) -> None:
        """扫码完成后告诉用户结果。

        两条路，按可靠性排：

        1. 用原始事件回复。带 msg_id 走的是被动回复，不需要主动消息权限。
           QQ 官方 bot 在群里的主动消息要群授权、每条还消耗额度，实测报
           「主动消息失败, 无权限」（40034105），所以这条路必须先试。
           代价是有时效——扫码久了 msg_id 就失效了。
        2. 用会话标识主动发。作为兜底，但在群里同样可能被拒。

        两条都不通时只记日志。用户可以发 /爱农 状态 自己查。
        """
        from astrbot.api.message_components import Plain
        from astrbot.core.message.message_event_result import MessageChain

        await self._发消息(用户, MessageChain(chain=[Plain(文本)]))

    async def _通知图片(self, 用户: str, 图片: str, 文本: str) -> None:
        """推一张新二维码。QQ 的码两分钟就过期，换码必须真的发出去。"""
        结果 = MessageEventResult().message(文本).base64_image(图片)
        await self._发消息(用户, 结果)

    async def _发消息(self, 用户: str, 消息: Any) -> None:
        """按可靠性依次尝试被动回复与主动发送，见 `_通知` 的说明。"""
        事件 = self._事件.get(用户)
        if 事件 is not None:
            try:
                await 事件.send(消息)
                return
            except Exception as exc:
                logger.info(f"[ainong] 被动回复失败，试主动发送：{type(exc).__name__}: {exc}")

        会话标识 = self._会话标识.get(用户)
        if not 会话标识:
            return
        try:
            await self.context.send_message(会话标识, 消息)
        except Exception as exc:
            logger.warning(f"[ainong] 主动通知用户失败：{type(exc).__name__}: {exc}")

    @爱农.command("解绑")
    async def 解绑(self, event: AstrMessageEvent):
        """解除绑定并删除凭据。"""
        用户 = event.get_sender_id()
        await self._清理会话(用户, self._扫码会话.pop(用户, None))

        记录 = self._凭据.删除(用户)
        if not 记录:
            yield event.plain_result("你还没有绑定营地账号。")
            return
        yield event.plain_result(f"已解绑，凭据已删除（营地账号 {记录['营地ID']}）。")

    @爱农.command("状态", alias={"status"})
    async def 状态(self, event: AstrMessageEvent):
        """看当前绑定与扫码会话的情况。排查用。"""
        用户 = event.get_sender_id()
        记录 = self._凭据.读取(用户)

        行 = [f"你的标识：{用户 or '（拿不到）'}"]
        if 记录:
            昵称 = str(记录.get("昵称") or "").strip()
            行.append(
                f"已绑定营地账号 {记录['营地ID']}"
                + (f"（{昵称}）" if 昵称 else "")
                + f"，当前角色 {记录.get('角色ID') or '（未选择，用 /爱农 角色 选）'}"
            )
        else:
            行.append("未绑定营地账号，发 /爱农 绑定QQ 或 /爱农 绑定微信 开始。")

        if 用户 in self._扫码会话:
            行.append("有一个扫码会话在进行中。卡住的话发 /爱农 解绑 清掉它。")

        yield event.plain_result("\n".join(行))

    @爱农.command("昵称")
    async def 昵称(self, event: AstrMessageEvent, 名字: GreedyStr):
        """设置 PK 用的名字。

        绑定时会自动记下平台给的显示名，但那个值不可靠：QQ 官方接口回的是 QQ
        昵称而不是群昵称，实测有人是「……」。所以留一个自己设的出口。
        """
        用户 = event.get_sender_id()
        记录 = self._凭据.读取(用户)
        if not 记录:
            yield event.plain_result("还没绑定营地账号，先发 /爱农 绑定QQ 或 /爱农 绑定微信。")
            return

        新名 = str(名字 or "").strip()
        if not 新名:
            yield event.plain_result(
                f"你现在的 PK 名字是「{记录.get('昵称') or '（没设）'}」。"
                "发 /爱农 昵称 <名字> 改一个。"
            )
            return
        if len(新名) > _昵称上限:
            yield event.plain_result(f"名字太长了，{_昵称上限} 个字以内。")
            return

        记录["昵称"] = 新名
        self._凭据.写入(用户, 记录)
        yield event.plain_result(f"好，以后群友发 /爱农 PK {新名} 就能点你。")

    # ---------------------------------------------------------------- 查询

    @爱农.command("角色")
    async def 角色(self, event: AstrMessageEvent, 角色ID: GreedyStr):
        """列出该营地账号下的游戏角色。不带参数时只列出，带角色ID则切换到它。"""
        用户 = event.get_sender_id()
        记录 = self._凭据.读取(用户)
        if not 记录:
            yield event.plain_result("还没绑定营地账号，先发 /爱农 绑定。")
            return

        参数 = str(角色ID).strip()

        async with 营地传输() as 传输:
            传输.绑定账号(**{k: 记录[k] for k in ("营地ID", "令牌", "对称密钥")})
            try:
                列表 = await 传输.取角色列表()
            except Exception as exc:
                yield event.plain_result(f"取角色列表失败：{exc}")
                return

        if not 列表:
            yield event.plain_result("这个营地账号下没有游戏角色。")
            return

        if not 参数:
            当前 = self._凭据.当前角色(用户)
            行 = [
                f"{'（当前）' if 角色['角色ID'] == 当前 else ''}{角色['名称']}"
                f"｜{角色['区服描述']}｜{角色['角色ID']}"
                for 角色 in 列表
            ]
            yield event.plain_result(
                "游戏角色：\n" + "\n".join(行) + "\n\n发 /爱农 角色 <角色ID> 切换。"
            )
            return

        匹配 = next((角色 for 角色 in 列表 if 角色["角色ID"] == 参数), None)
        if 匹配 is None:
            可用 = "、".join(角色["角色ID"] for 角色 in 列表)
            yield event.plain_result(f"没有这个角色。可选：{可用}")
            return

        self._凭据.选角色(用户, 匹配["角色ID"])
        yield event.plain_result(
            f"已切到{匹配['名称']}（{匹配['区服描述']}）。发 /爱农 战绩 看这个角色的数据。"
        )

    @爱农.command("战绩")
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

    @爱农.command("锐评")
    async def 锐评(self, event: AstrMessageEvent):
        """让模型基于近期战绩给一段评价。"""
        数据 = await self._读战绩(event.get_sender_id())
        if self._战绩不可用(数据):
            yield event.plain_result(数据)
            return

        try:
            提供方 = await self.context.get_current_chat_provider_id(event.unified_msg_origin)
        except Exception as exc:
            yield event.plain_result(f"取不到当前对话用的模型：{exc}")
            return

        try:
            结果 = await self.context.tool_loop_agent(
                event=event,
                chat_provider_id=提供方,
                prompt=锐评提示(数据),
                max_steps=8,
            )
        except Exception as exc:
            logger.warning(f"[ainong] 锐评失败：{type(exc).__name__}: {exc}")
            yield event.plain_result(f"锐评失败：{exc}")
            return

        yield event.plain_result(结果.completion_text or "模型没有返回内容。")

    @爱农.command("开一局", alias={"开一局排位"})
    async def 开一局(self, event: AstrMessageEvent):
        """按他近期的数据推演一局排位。

        胜负由 `抽对局结果` 按真实胜率抽好再交给模型——让模型自己定的话，
        它每次都会写「超神带飞」，一个 45% 胜率的号不该这样。
        """
        用户 = event.get_sender_id()
        记录 = self._凭据.读取(用户)
        if 记录 is None:
            yield event.plain_result("还没绑定营地账号，先发 /爱农 绑定QQ 或 /爱农 绑定微信。")
            return

        数据, 统计 = await self._读战绩与统计(记录, 标签=用户)
        if self._战绩不可用(数据):
            yield event.plain_result(数据)
            return
        if not 统计.get("总场次"):
            yield event.plain_result("还没有可查的近期战绩，开不了局。")
            return

        try:
            提供方 = await self.context.get_current_chat_provider_id(event.unified_msg_origin)
        except Exception as exc:
            yield event.plain_result(f"取不到当前对话用的模型：{exc}")
            return

        try:
            结果 = await self.context.tool_loop_agent(
                event=event,
                chat_provider_id=提供方,
                prompt=开一局提示(数据, 抽对局结果(统计)),
                max_steps=8,
            )
        except Exception as exc:
            logger.warning(f"[ainong] 开一局失败：{type(exc).__name__}: {exc}")
            yield event.plain_result(f"开一局失败：{exc}")
            return

        yield event.plain_result(结果.completion_text or "模型没有返回内容。")

    @爱农.command("PK", alias={"pk", "对战"})
    async def PK(self, event: AstrMessageEvent, 目标: GreedyStr):
        """和另一个人比近期战绩。

        对手的定位顺序：先看消息里的 @ 或标识，再按群昵称找人。**QQ 官方平台
        拿不到被 @ 的人的标识**——适配器只把「@机器人」转成组件，@别人在事件里
        连痕迹都没有（实测组件是 `['qq_official', None]`、正文是 `'爱农 PK'`），
        所以昵称才是这个平台上的主路径。

        查对手战绩走「记录」而不是「用户标识」：凭据里本来就够用，老的绑定
        记录也没存过标识。
        """
        自己 = event.get_sender_id()
        自己记录 = self._凭据.读取(自己)
        if 自己记录 is None:
            yield event.plain_result("你还没绑定营地账号，先发 /爱农 绑定QQ 或 /爱农 绑定微信。")
            return

        参数 = str(目标 or "").strip()
        对手 = 找对手(
            event.get_messages(),
            f"{参数} {getattr(event, 'message_str', '') or ''}",
            自己=自己,
            机器人=self._机器人标识(event),
        )
        对手记录 = self._凭据.读取(对手) if 对手 else None

        # 捡到的标识没绑定过，多半用户其实写的是昵称。按名字再找一遍。
        if 对手记录 is None and 参数:
            匹配 = self._凭据.按昵称找(参数)
            if len(匹配) > 1:
                名字 = "、".join(str(记录.get("昵称") or "?") for 记录 in 匹配)
                yield event.plain_result(f"有不止一个叫「{参数}」的：{名字}。写完整一点再试。")
                return
            if 匹配:
                对手记录 = 匹配[0]
                对手 = str(匹配[0].get("用户") or "") or 对手

        自己记录 = self._凭据.读取(自己)
        if 对手记录 is not None and self._同一个账号(自己记录, 对手记录):
            yield event.plain_result("这跟你的绑定是同一个营地账号，比不出高下。找个群友。")
            return

        if 对手记录 is None:
            # 各平台 @ 人的形态差别极大，QQ 官方平台干脆什么都不给，所以把实际
            # 拿到的东西记下来——否则只能靠猜。
            logger.info(
                "[ainong] PK 找不到对手：参数=%r 组件=%r 正文=%r 自己=%r",
                参数,
                [getattr(组件, "qq", None) for 组件 in event.get_messages() or []],
                str(getattr(event, "message_str", "") or ""),
                自己,
            )
            yield event.plain_result(_PK用法)
            return

        自己数据, 自己统计 = await self._读战绩与统计(自己记录, 标签=自己)
        if self._战绩不可用(自己数据):
            yield event.plain_result(自己数据)
            return
        对手数据, 对手统计 = await self._读战绩与统计(对手记录)
        if self._战绩不可用(对手数据):
            yield event.plain_result("读不到对方的数据，可能他没选角色或关了战绩展示。")
            return
        if not 自己统计.get("总场次") or not 对手统计.get("总场次"):
            yield event.plain_result("有一方没有可查的近期战绩，比不了。")
            return

        try:
            提供方 = await self.context.get_current_chat_provider_id(event.unified_msg_origin)
        except Exception as exc:
            yield event.plain_result(f"取不到当前对话用的模型：{exc}")
            return

        自己名 = self._显示名(event.get_sender_name(), "你")
        对手名 = self._显示名(str(对手记录.get("昵称") or ""), "对手")

        # 逐项对比在这里**算死**再交给模型解说。让模型自己比，它最省事的答案
        # 就是「各有千秋」——线上实测真出过 83 对 87 这种看不出输赢的分。
        要点 = 对比要点(自己名, 自己统计, 对手名, 对手统计)
        提示 = PK提示(
            自己名,
            对手名,
            对比文本(要点, 自己名, 对手名),
            占优项数(要点, 自己名, 对手名),
            自己数据,
            对手数据,
        )

        try:
            结果 = await self.context.tool_loop_agent(
                event=event,
                chat_provider_id=提供方,
                prompt=提示,
                max_steps=8,
            )
        except Exception as exc:
            logger.warning(f"[ainong] PK 失败：{type(exc).__name__}: {exc}")
            yield event.plain_result(f"PK 失败：{exc}\n\n两人的数据：\n\n{自己数据}\n\n{对手数据}")
            return

        yield event.plain_result(结果.completion_text or "模型没有返回内容。")

    @staticmethod
    def _战绩不可用(文本: str) -> bool:
        """`_读战绩` 失败时返回的是给人看的整句话，不是数据。"""
        return 文本.startswith(("提问者还没有", "读取战绩失败"))

    @staticmethod
    def _显示名(候选: str, 兜底: str) -> str:
        return 候选.strip() or 兜底

    @staticmethod
    def _机器人标识(event: AstrMessageEvent) -> str:
        """机器人自己的标识。群里 @机器人 会产生 At 组件，得把它排掉。"""
        try:
            return str(event.get_self_id() or "")
        except Exception:
            return ""

    async def _读战绩(self, 用户: str) -> str:
        记录 = self._凭据.读取(用户)
        if not 记录:
            return "提问者还没有绑定王者营地账号，无法查询战绩。"
        return await self._读战绩用记录(记录, 标签=用户)

    async def _读战绩用记录(self, 记录: dict[str, Any], *, 标签: str = "") -> str:
        """只要文本。战绩、锐评用。"""
        return (await self._读战绩与统计(记录, 标签=标签))[0]

    async def _读战绩与统计(
        self, 记录: dict[str, Any], *, 标签: str = ""
    ) -> tuple[str, dict[str, Any]]:
        """返回 (给模型读的文本, 统计字典)。

        PK 要的是**统计字典**：两个人的逐项对比得由代码算（`stats.对比要点`），
        不能把两份文本丢给模型让它自己比——那样它会端水。
        """
        async with 营地传输() as 传输:
            传输.绑定账号(**{k: 记录[k] for k in ("营地ID", "令牌", "对称密钥")})
            try:
                return await 读战绩数据(传输, 记录.get("角色ID") or "")
            except Exception as exc:
                谁 = 标签 or 记录.get("营地ID")
                logger.warning(f"[ainong] 读战绩失败（{谁}）：{type(exc).__name__}: {exc}")
                return f"读取战绩失败：{exc}", {}

    @staticmethod
    def _同一个账号(甲: dict[str, Any] | None, 乙: dict[str, Any] | None) -> bool:
        """两份绑定指向同一个营地账号。自己没绑定时不算。"""
        if not 甲 or not 乙:
            return False
        return str(甲.get("营地ID")) == str(乙.get("营地ID"))
