"""main.py 里几处顺序与接线约束。

这些规则本地跑不了——main.py 顶层 import astrbot，而开发环境没这个包，
装上又会把整个插件的依赖拖进测试环境。所以按源码检查。

**`_通知` 必须在 `_清理会话` 之前。** 通知依赖 `_事件` 与 `_会话标识`，
清理会把两者丢掉，顺序一反通知就发不出去。这个坑已经踩过一次：
`_扫码失败` 里先清理再通知，事件已被 pop，只能靠日志才发现。

`main.py` 的导入与指令注册也一并检查，避免同类问题再次溜过去。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

入口 = Path(__file__).resolve().parent.parent / "main.py"
源码 = 入口.read_text(encoding="utf-8")
树 = ast.parse(源码)


def _方法节点(类名: str, 方法名: str):
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.ClassDef) and 节点.name == 类名:
            for 项 in 节点.body:
                if isinstance(项, (ast.FunctionDef, ast.AsyncFunctionDef)) and 项.name == 方法名:
                    return 项
    raise AssertionError(f"main.py 里找不到 {类名}.{方法名}")


def _方法体(类名: str, 方法名: str) -> list[ast.stmt]:
    return _方法节点(类名, 方法名).body


def _方法源码(类名: str, 方法名: str) -> str:
    """整个方法的**代码**（含装饰器、含嵌套函数），注释不带。

    走 `ast.unparse` 而不是 `ast.get_source_segment`：后者会把注释一起带进来，
    于是注释里写个 `self._完成` 就能让 `"... not in 片段"` 这类断言误报——
    这条已经踩过一次（bug 修好了，测试反而红）。
    """
    节点 = _方法节点(类名, 方法名)
    return ast.unparse(节点)


def _调用的方法(方法名: str) -> list[ast.Call]:
    """在某个方法体里找到对指定方法的调用，按顺序返回行号。"""
    行号 = []
    for 节点 in _方法体("Main", 方法名):
        for 子 in ast.walk(节点):
            if isinstance(子, ast.Call) and isinstance(子.func, ast.Attribute):
                if 子.func.attr == 方法名:
                    行号.append(子.lineno)
    return 行号


def test_入口能解析():
    assert 源码, "main.py 读出来是空的"


def test_通知在清理之前调用():
    """_通知 依赖 _事件 与 _会话标识，清理会 pop 掉它们。"""
    片段 = _方法源码("Main", "_收到授权码")
    最后一次通知 = 片段.rfind("_通知(")
    清理位置 = 片段.rfind("_清理会话(")
    assert 最后一次通知 != -1, "_收到授权码 里没有 _通知 调用"
    assert 清理位置 != -1, "_收到授权码 里没有 _清理会话 调用"
    assert 最后一次通知 < 清理位置, (
        "_收到授权码 里 _清理会话 出现在 _通知 之前，通知会被清掉的事件与标识"
    )


def test_扫码失败里也是先通知再清理():
    """_扫码失败 里的顺序同样关键，这里最容易写反。"""
    片段 = _方法源码("Main", "_扫码失败")
    通知 = 片段.rfind("_通知(")
    清理 = 片段.rfind("_清理会话(")
    assert 通知 != -1, "_扫码失败 里没有 _通知 调用"
    assert 清理 != -1, "_扫码失败 里没有 _清理会话 调用"
    assert 通知 < 清理, "_扫码失败 里先清理再通知，事件已被 pop，通知发不出去"


def test_清理会话清掉三样东西():
    """事件、会话标识、会话，三样都归它管。漏一样就会漏通知或泄漏对象。"""
    for 行 in _方法体("Main", "_清理会话"):
        if isinstance(行, ast.Expr) and isinstance(行.value, ast.Await):
            行 = 行.value.value
        if isinstance(行, ast.Call) and isinstance(行.func, ast.Attribute):
            if 行.func.attr == "pop" and isinstance(行.func.value, ast.Attribute):
                assert 行.func.value.attr in {"_事件", "_会话标识"}, (
                    f"_清理会话 里 pop 了 {行.func.value.attr}，只该清 _事件 与 _会话标识"
                )


def test_回调是单参协程():
    """等授权码 按单参调用回调，传双参进去就是 TypeError。"""
    片段 = _方法源码("Main", "_绑定")
    assert "def _完成(" in 片段, "绑定 里的回调应是只收一个参数的协程"
    assert "self._收到授权码(用户," in 片段, "回调里要把用户标识传下去"
    # 不能直接把双参方法当回调传出去
    assert "开始等待(self._收到授权码" not in 片段, (
        "别把 _收到授权码 直接当回调传，等授权码 只传一个参数"
    )


def test_QQ_回调要_await_换票():
    """QQ 那条的回调必须是协程，且 `换取平台凭据` 要 await。

    v0.1.8 线上这行写的是 `lambda code: self._完成(换取平台凭据(code))`，两个
    错叠在一起：

    - `_完成` 是 `_绑定` 里的**局部函数**，`self._完成` 直接 AttributeError；
    - `换取平台凭据` 是协程函数，不 await 只会构造出一个没被 await 的协程对象
      当参数传下去，营地登录那层拿到的是 coroutine 而不是凭据字典。

    两者都发生在**扫码成功之后**，表现是"扫完了却报错、绑不上"，日志里只有
    一行 `扫码等待失败`。
    """
    片段 = _方法源码("Main", "_绑定")
    assert "self._完成" not in 片段, "`_完成` 是局部函数，写 self._完成 会 AttributeError"
    assert "await 换取平台凭据(" in 片段, "换票必须 await，否则传下去的是协程对象"


def test_有状态指令():
    """扫码过程用户看不到结果，需要能自己查。"""
    指令 = _指令集()
    assert {"绑定微信", "绑定QQ", "解绑", "战绩", "状态", "帮助"} <= 指令, (
        f"指令不全：{sorted(指令)}"
    )


def _指令集() -> set[str]:
    指令: set[str] = set()
    for 节点 in ast.walk(树):
        if isinstance(节点, ast.Call) and isinstance(节点.func, ast.Attribute):
            if 节点.func.attr == "command" and 节点.args:
                第一个 = 节点.args[0]
                if isinstance(第一个, ast.Constant) and isinstance(第一个.value, str):
                    指令.add(第一个.value)
    return 指令


def test_PK_从消息里找对手而不是命令参数():
    """PK 的对手要从消息里捡。

    群里 @ 一个人，多数平台把它放进消息组件而不是命令参数，参数常常是空的；
    QQ 官方平台更极端——@别人根本不生成组件，只有正文里一段 `<@!id>`。
    所以对手必须用 `找对手` 从组件+正文里捡，不能只读 `目标`。
    """
    片段 = _方法源码("Main", "PK")
    assert "找对手(event.get_messages()" in 片段.replace("\n", ""), (
        "对手要用 找对手 从消息里捡，别只读命令参数"
    )
    assert "get_self_id" in _方法源码("Main", "_机器人标识"), (
        "要把机器人自己的标识排掉，否则「@机器人 PK @某人」会拿机器人当对手"
    )


def test_PK_支持按昵称找对手():
    """昵称是 QQ 官方平台上的主路径。

    实测：群里 @ 别人时，事件里的组件是 `['qq_official', None]`、正文是
    `'爱农 PK'` —— 被 @ 的人的标识**完全不出现**。所以只靠 @ 的话这个平台上
    根本点不到人，必须能按昵称找，而且找到后只有记录没有标识，得能按记录查。
    """
    片段 = _方法源码("Main", "PK")
    assert "按昵称找" in 片段, "只靠 @ 定位对手，在 QQ 官方平台用不了"
    assert "_读战绩与统计" in 片段, "对手只有凭据记录，没有用户标识"
    assert "对比要点" in 片段, "逐项对比要由代码算，交给模型它会端水"


def test_绑定有微信与_qq_两条():
    """两条授权路径是分开的：微信纯 HTTP，QQ 要浏览器侧车。

    别合成一个「绑定」再靠参数选——QQ 那条在侧车不可用时要给明确错误，
    合成一条就只能说「绑定失败」。
    """
    指令 = _指令集()
    assert "绑定微信" in 指令
    assert "绑定QQ" in 指令
    assert "绑定" not in 指令, "绑定应该拆成两条，别用一个入口混着选"


def test_绑定_保留旧指令_作别名():
    """老用户发 /爱农 绑定 不该突然失效——它是 绑定微信 的别名。"""
    for 节点 in ast.walk(树):
        if not isinstance(节点, ast.AsyncFunctionDef):
            continue
        if 节点.name not in ("绑定微信", "绑定QQ"):
            continue
        别名: set[str] = set()
        for 装饰器 in 节点.decorator_list:
            if isinstance(装饰器, ast.Call) and isinstance(装饰器.func, ast.Attribute):
                if 装饰器.func.attr != "command":
                    continue
                for 关键字 in 装饰器.keywords:
                    if 关键字.arg == "alias" and isinstance(关键字.value, ast.Set):
                        别名 = {
                            e.value
                            for e in 关键字.value.elts
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)
                        }
        assert "绑定" in 别名 or "绑定qq" in 别名, (
            f"{节点.name} 没有保留旧指令名作别名，会让老用户的 /爱农 绑定 失效"
        )


def test_侧车地址来自配置():
    """QQ 要连侧车，地址不能硬编码——部署时容器名可能不同。"""
    片段 = _方法源码("Main", "_侧车地址")
    assert "self.config.get" in 片段, "侧车地址应从配置读，不要写死"


def test_有改昵称的指令():
    """绑定时自动记的平台名不可靠。

    QQ 官方接口回的是 QQ 昵称而不是群昵称，实测服务器上有人是「……」——
    照那个名字 PK 根本点不到人。所以要有自己设的出口。
    """
    assert "昵称" in _指令集(), "缺 /爱农 昵称，PK 名字没法自己定"


def test_昵称写入的是凭据记录而不是别处():
    """PK 按昵称找人走的是凭据仓库，名字要落在同一份记录里。"""
    片段 = _方法源码("Main", "昵称")
    assert "_凭据.写入" in 片段, "名字要写进凭据记录，否则 PK 找不到"
    assert "昵称" in 片段


def test_有开一局指令():
    assert "开一局" in _指令集(), "缺 /爱农 开一局"


def test_开一局胜负由代码抽():
    """胜负不交给模型定：模型没有随机性，连开十局都是「超神带飞」。"""
    片段 = _方法源码("Main", "开一局")
    assert "抽对局结果" in 片段, "胜负要按真实胜率抽好再交给模型"
    assert "开一局提示" in 片段


class Test日志出口:
    """插件规范：logger 必须且只能从 `astrbot.api` 取，不许用内置 `logging`。

    上架审核第一次就是被这一条驳回的——`ainong/auth/` 下两个模块用了内置
    `logging`，而 main.py 与 camp/ 都是干净的，只看 main.py 查不出来，
    所以这里扫整个包。
    """

    def test_包内不用内置logging(self):
        违规 = [
            路径.name
            for 路径 in sorted(入口.parent.joinpath("ainong").rglob("*.py"))
            if re.search(r"^\s*(?:import logging|from logging)\b", 路径.read_text("utf-8"), re.M)
        ]
        assert not 违规, f"这些文件用了内置 logging，要改成从 astrbot.api 取：{违规}"

    def test_logger_从_astrbot_取(self):
        assert re.search(r"^from astrbot\.api import .*\blogger\b", 源码, re.M)

    def test_日志出口自己从_astrbot_取(self):
        """auth/ 与 camp/ 不 import astrbot，日志出口必须自己从框架取。

        审核规则是「logger 必须且只能从 astrbot.api 导入」。钩子只在本地单测
        里接管，运行期由 `日志.py` 直接拿框架 logger。
        """
        出口 = (入口.parent / "ainong" / "日志.py").read_text(encoding="utf-8")
        assert re.search(r"^\s*from astrbot\.api import logger", 出口, re.M)
        assert not re.search(r"^\s*(?:import|from)\s+logging\b", 出口, re.M)


class Test有没有数据靠返回值判断:
    """不能靠文本前缀判断数据可用性。

    这个角色没有可查的近期战绩时，`汇总文本` 返回的是一句「这个角色还没有可查的
    近期战绩。」，它既不以「还没绑定」也不以「读取战绩失败」开头。靠前缀判断的话
    锐评会把这句当成数据喂给模型，而锐评提示要求写够 3 个具体数字，模型只能编。
    """

    def test_读战绩返回文本与统计字典(self):
        片段 = _方法源码("Main", "_读战绩")
        assert "tuple[str, dict[str, Any] | None]" in 片段
        assert "'还没绑定，先发 /爱农 绑定微信 或 绑定QQ。', None" in 片段

    def test_没有场次时统计字典是_None(self):
        片段 = _方法源码("Main", "_读战绩与统计")
        assert "return (文本, None)" in 片段
        assert "return (f'读取战绩失败：{exc}', None)" in 片段

    def test_锐评看统计字典而不是文本(self):
        assert "if 统计 is None:" in _方法源码("Main", "锐评")

    def test_开一局看统计字典(self):
        assert "if 统计 is None:" in _方法源码("Main", "开一局")

    def test_PK_两边都看统计字典(self):
        片段 = _方法源码("Main", "PK")
        assert "if 自己统计 is None:" in 片段
        assert "if 对手统计 is None:" in 片段

    def test_前缀判断已经不在了(self):
        """那个判断被统计字典取代了，留着会有人以为还能用。"""
        assert "_战绩不可用" not in 源码


def _别名集() -> set[str]:
    """类体里 `@爱农.command("x", alias={...})` 声明的全部名字与别名。"""
    出: set[str] = set()
    for 节点 in ast.walk(树):
        if not isinstance(节点, ast.Call) or not isinstance(节点.func, ast.Attribute):
            continue
        if 节点.func.attr != "command" or not 节点.args:
            continue
        第一个 = 节点.args[0]
        if isinstance(第一个, ast.Constant) and isinstance(第一个.value, str):
            出.add(第一个.value)
        for 关键字 in 节点.keywords:
            if 关键字.arg == "alias" and isinstance(关键字.value, ast.Set):
                出.update(
                    e.value
                    for e in 关键字.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                )
    return 出


def _帮助块() -> str:
    起点 = 源码.index('_帮助文本 = """') + len('_帮助文本 = """')
    return 源码[起点 : 源码.index('"""', 起点)]


class Test帮助文案:
    def test_每个指令都在帮助里(self):
        """帮助漏一条，用户就只能靠猜或问。"""
        缺 = sorted(名 for 名 in _指令集() if f"/爱农 {名}" not in _帮助块())
        assert not 缺, f"帮助文本里没列这些指令：{缺}"

    def test_帮助首行是产品名加游戏名(self):
        assert _帮助块().lstrip().startswith("爱农 · ")

    def test_标题写明数据来自哪里(self):
        """文案收成一行一句后，数据来源只留在标题里。"""
        assert "王者营地" in _帮助块().splitlines()[0]

    def test_说明自然语言也能用(self):
        assert "自然语言" in _帮助块()


class Test落空兜底:
    def test_指令组挂了兜底过滤器(self):
        """指令落空时消息会原样进模型，模型收到普通提问就开始编。"""
        for 节点 in ast.walk(树):
            if isinstance(节点, ast.ClassDef) and 节点.name == "Main":
                for 项 in 节点.body:
                    if isinstance(项, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        assert any(
                            "custom_filter" in ast.unparse(装饰) for 装饰 in 项.decorator_list
                        ), "指令组方法上要挂 @custom_filter(_落空兜底)"
                        return
        raise AssertionError("main.py 里没有 Main 类")

    def test_兜底别名清单与指令一致(self):
        """`ainong.兜底.子命令名` 是手抄的，main.py 改了别名忘了改它，
        用户打那个别名就会拿到一句「不是子命令」。"""
        from ainong.兜底 import 子命令名

        实际 = _别名集()
        缺 = 实际 - 子命令名
        assert not 缺, f"这些指令/别名没写进 兜底.子命令名：{sorted(缺)}"

    def test_组别名带上斜杠(self):
        """QQ 官方的 At 唤醒分支不剥 message_str 里的 `/`。

        那条分支只置 `wake_prefix = ""`，于是 `@机器人 /爱农 战绩` 的
        message_str 仍是 `/爱农 战绩`，组名 `爱农` 匹配不上，整条指令静默
        失败。加一个带斜杠的组别名，两种写法都能进。
        """
        assert "_组别名" in 源码
        assert 'f"/{_组名}"' in 源码

    def test_兜底_filter_只_return_True(self):
        """`CustomFilter.filter` 返回 False 会让整个指令组被跳过。

        返回值语义是「这条消息我管不管」，不是「命中没有」。写成「命中返回
        False」时 `/爱农 战绩` 完全没反应。
        """
        方法 = _方法节点("_落空兜底", "filter")
        返回 = [
            节点.value.value
            for 节点 in ast.walk(方法)
            if isinstance(节点, ast.Return) and isinstance(节点.value, ast.Constant)
        ]
        assert 返回 and set(返回) == {True}, f"兜底 filter 里出现了 {返回}，必须只 return True"
        # 命中必须掐掉事件，否则消息照样漏给模型
        assert "event.stop_event()" in ast.unparse(方法)
        # 必须先判「关不关我事」再动手，否则会掐掉别的插件的指令
        assert "以组名开头" in ast.unparse(方法)


class Test源码卫生:
    """两类只在运行时才炸、本地又跑不到的写法。

    漏 f 前缀的字符串**语法完全合法**，只有用户看到字面量 `{名字}` 时才知道
    出事了；except 里读 try 体内才绑定的变量同样合法，只有异常真发生时才
    `UnboundLocalError`。
    """

    def test_没有漏f前缀的字符串(self):
        占位 = re.compile(r"\{[^{}\n]{1,40}\}")
        漏 = [
            (节点.lineno, 命中.group(0))
            for 节点 in ast.walk(树)
            if isinstance(节点, ast.Constant) and isinstance(节点.value, str)
            for 命中 in 占位.finditer(节点.value)
        ]
        assert not 漏, f"这些字符串里的占位符不会被替换（漏了 f 前缀）：{漏}"

    def test_except里不读try体内才绑定的变量(self):
        问题 = []
        for 函数 in [
            节点
            for 节点 in ast.walk(树)
            if isinstance(节点, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]:
            for 函数名, 行号, 名字 in _未绑定读取(函数):
                问题.append(f"{函数名} 第{行号}行 except 里读了 {sorted(名字)}")
        assert not 问题, "\n".join(问题)


def _绑定的(节点们: list[ast.AST]) -> set[str]:
    出: set[str] = set()
    for 节点 in 节点们:
        for 子 in ast.walk(节点):
            if isinstance(子, ast.Name) and isinstance(子.ctx, ast.Store):
                出.add(子.id)
            if isinstance(子, (ast.FunctionDef, ast.AsyncFunctionDef)):
                出.add(子.name)
            if isinstance(子, ast.ExceptHandler) and 子.name:
                出.add(子.name)
    return 出


def _未绑定读取(函数: ast.AsyncFunctionDef | ast.FunctionDef) -> list[tuple[str, int, set]]:
    """找出 `except` 里读了「同一个 try 体内才绑定」的变量的地方。"""
    报告: list[tuple[str, int, set]] = []
    已绑 = {参数.arg for 参数 in 函数.args.args}

    def 扫(节点们: list[ast.stmt]) -> None:
        for 节点 in 节点们:
            if isinstance(节点, ast.Try):
                体内 = _绑定的(节点.body)
                for 处理 in 节点.handlers:
                    读到 = {
                        子.id
                        for 子 in ast.walk(处理)
                        if isinstance(子, ast.Name) and isinstance(子.ctx, ast.Load)
                    }
                    可疑 = (读到 & 体内) - 已绑
                    if 可疑:
                        报告.append((函数.name, 节点.lineno, 可疑))
                扫(节点.body)
                for 处理 in 节点.handlers:
                    扫(处理.body)
                    已绑.update(_绑定的(处理.body))
                扫(节点.orelse)
                扫(节点.finalbody)
                已绑.update(体内)
            elif hasattr(节点, "body") and isinstance(节点.body, list):
                已绑.update(_绑定的([节点]))
                扫(节点.body)

    扫(函数.body)
    return 报告


class Test审核合规:
    """市场审核的硬要求：数据目录必须是 `plugin_data/<plugin_name>`。"""

    def test_数据目录用插件名(self):
        assert "StarTools.get_data_dir(_插件名)" in 源码
        assert '_插件名 = "astrbot_plugin_ainong"' in 源码
        assert '"plugin_data" / "ainong"' not in 源码

    def test_旧目录会被迁移(self):
        assert "_迁移旧凭据(目录)" in 源码
        assert '_旧数据目录名 = "ainong"' in 源码


class Test空指令给帮助:
    """只发 `/爱农` 时回帮助，别甩框架的「参数不足」。

    2026-10-29 实测（爱瓦）：`/爱瓦 @某人` 落到框架那层，回的是「参数不足」
    加全部子命令和各自的 docstring——一大段内部说明，用户还是不知道能发什么。
    """

    def test_只发组名算空指令(self):
        from ainong.兜底 import 是否空指令

        for 消息 in ("/爱农", "爱农", "/爱农   ", "爱农 "):
            assert 是否空指令(消息, "爱农"), 消息

    def test_带参数或别人的消息不算(self):
        from ainong.兜底 import 是否空指令

        for 消息 in ("/爱农 战绩", "爱农战绩", "/爱瓦 状态", "今天天气不错", ""):
            assert not 是否空指令(消息, "爱农"), 消息

    def test_过滤器回帮助而不是落空提示(self):
        体 = 源码[源码.index("class _落空兜底") :]
        体 = 体[: 体.index("class Main(")]
        assert "是否空指令(" in 体
        assert "_帮助文本" in 体, "空指令要回帮助，不能只说「不是子命令」"
