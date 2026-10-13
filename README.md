<div align="center">
  <img src="logo.png" alt="爱农" width="128">
</div>

# 爱农

[![AstrBot](https://img.shields.io/badge/AstrBot-插件-4D7AFF)](https://github.com/AstrBotDevs/AstrBot)
[![QQ](https://img.shields.io/badge/QQ-支持-12B7F5?logo=qq&logoColor=white)](https://github.com/AstrBotDevs/AstrBot)
[![微信](https://img.shields.io/badge/微信-支持-07C160?logo=wechat&logoColor=white)](https://github.com/AstrBotDevs/AstrBot)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/许可-WTFPL-9CA3AF?logo=open-source-initiative&logoColor=white)](LICENSE)

查王者营地战绩，让模型替你锐评。

AstrBot 插件。扫码绑定自己的王者营地账号后，问它就能拿到段位、战绩、英雄池，
由对话模型给出评价。

## 数据来自哪

本插件通过王者营地的接口读取数据。腾讯没有开放面向第三方的玩家数据接口，
这里用的是营地客户端自己的接口，**需要扫码登录一次**（微信或 QQ 两条路）。

营地账号可以设置战绩是否对外展示。对方关闭时查询会失败，插件会说明原因，
不做绕过。数据仅用于个人查询，请勿用于批量抓取。

## 主要功能

- 扫码绑定自己的营地账号，账号下的多个游戏角色可切换
- `/爱农 战绩`：段位星数、巅峰分、胜率、KDA、奖牌、一血超神、最近 10 场走势
- `/爱农 锐评`：先给一句称号，再说打得好／问题／建议
- `/爱农 PK <名字>`：和群友比一把，模型给趣味分并互损
- `/爱农 开一局`：推演他下一局排位的过程与结果
- 每人一份凭据，互不可见，解绑即删

## 安装

把仓库放进 AstrBot 的 `data/plugins/` 目录，重载插件。AstrBot 会读取
`requirements.txt` 自动装依赖，需要 Python 3.10 以上。

也可以在 AstrBot 面板的插件市场里按仓库地址安装。

## 配置

| 配置项 | 说明 |
|---|---|
| 扫码等待时长 | 从二维码发出开始计时，超时后需重新发指令 |
| 浏览器服务地址 | QQ 扫码用，默认 `http://playwright:3000`；容器名不同时才要改 |

## 使用

指令都在 `爱农` 指令组下，不占用通用名字。

```
/爱农 绑定微信          微信扫码绑定营地账号
/爱农 绑定QQ            手机 QQ 扫码绑定，需要浏览器侧车
/爱农 角色              列出游戏角色
/爱农 角色 <角色ID>     切换当前使用的角色
/爱农 战绩              当前角色的近期战绩
/爱农 锐评              让模型基于近期战绩给一段锐评（带称号）
/爱农 PK <名字>         和另一个人比近期战绩，模型给趣味分并点评
/爱农 昵称 <名字>       给自己起一个 PK 用的名字
/爱农 开一局            推演下一局排位的过程与结果
/爱农 解绑              解除绑定并删除凭据
/爱农 状态              看绑定情况与扫码进度
/爱农 帮助              列出全部指令
```

也可以直接用自然语言问，模型会调用本插件提供的工具读取提问者自己的战绩。

`/爱农 战绩` 给的是：段位与星数、巅峰分（打过巅峰赛才显示）、胜率、KDA、
MVP 占比、SVP、奖牌（金/银牌与主位置）、一血/超神/三杀、局内评价分布、
模式分布、英雄池、最近 10 场胜负走势与连胜连败。营地接口没返回的维度会直接
不显示，不会用 0 充数。

`/爱农 开一局` 是推演，**输出第一行会写明这一点**，不是真实战绩。

### 关于 PK

`/爱农 PK` 需要双方都绑定过营地账号，写对方的 **PK 名字**即可：

```
/爱农 昵称 老王        # 每个人自己起一次
/爱农 PK 老王
```

绑定时会自动取平台显示名当默认值，但那个值在 QQ 官方平台上是 **QQ 昵称而不是
群昵称**，可能是个「……」之类没法用的东西，所以留了 `/爱农 昵称` 自己改。

**@ 对方这条路在 QQ 官方平台走不通** —— 平台不把被 @ 的人的标识交给机器人
（实测收到的事件里既没有那个组件、正文里也没有痕迹）。在其它会传 @ 组件的
平台上，@ 与用户标识同样可以直接用。

### 角色与二维码

一个营地账号下可以有多个游戏角色（QQ 区与微信区、安卓与 iOS 是不同的角色）。
不指定角色时读的是营地侧返回的默认角色。

QQ 的二维码只有两分钟左右有效期，插件会在过期前自动换一张发给你，以最后收到
的那张为准；微信那张五分钟内都有效，不用管。

## 部署

QQ 扫码需要浏览器服务，微信扫码不需要：

- `deploy/compose.playwright.yaml` —— compose 片段，不暴露宿主机端口
- `deploy/seccomp-profile.json` —— 浏览器容器的 syscall 白名单

镜像从 `mcr.microsoft.com` 拉。国内网络需要走镜像源，否则 Docker 会因为
配了不可达的代理而拉取失败。

内存较小的机器上注意：一个 Chromium 会话常驻 300-500 MiB。

## 开发

```sh
uv sync --group qq-verify   # 装依赖
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

协作约定见 [AGENTS.md](AGENTS.md)，更新日志见 [docs/CHANGELOG.md](docs/CHANGELOG.md)，
术语定义见 [docs/GLOSSARY.md](docs/GLOSSARY.md)，发版流程见
[docs/RELEASING.md](docs/RELEASING.md)。

## License

[WTFPL](LICENSE)。
