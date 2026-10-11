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

AstrBot 插件。绑定自己的王者营地账号后，问它就能拿到段位、战绩、英雄池，
由对话模型给出评价。

## 主要功能

- 扫码绑定自己的营地账号，账号下的多个游戏角色可切换
- 近期战绩、段位、常用英雄与场均数据
- 把统计结果交给模型，写一段有话说的锐评
- 每人一份凭据，互不可见，解绑即删

## 安装

把仓库放进 AstrBot 的 `data/plugins/` 目录，重载插件。AstrBot 会读取
`requirements.txt` 自动装依赖，需要 Python 3.10 以上。

也可以在 AstrBot 面板的插件市场里按仓库地址安装。

## 配置

| 配置项 | 说明 |
|---|---|
| 扫码等待时长 | 从二维码发出开始计时。二维码本身有效期约五分钟，超时后需重新发指令 |

扫码全程走 HTTP，不需要浏览器。

## 使用

指令都在 `爱农` 指令组下，不占用通用名字。用户只发 `/爱农` 会看到完整指令树。

```
/爱农 绑定              扫码绑定营地账号
/爱农 角色              列出游戏角色
/爱农 角色 <角色ID>     切换当前使用的角色
/爱农 战绩              当前角色的近期战绩
/爱农 锐评              让模型基于近期战绩给一段评价
/爱农 解绑              解除绑定并删除凭据
```

也可以直接用自然语言问，模型会调用本插件提供的工具读取提问者自己的战绩。

一个营地账号下可以有多个游戏角色（QQ 区与微信区、安卓与 iOS 是不同的角色）。
不指定角色时读的是营地侧返回的默认角色。

## 部署

QQ 扫码需要浏览器服务，微信扫码不需要：

- `deploy/compose.playwright.yaml` —— compose 片段，不暴露宿主机端口
- `deploy/seccomp-profile.json` —— 浏览器容器的 syscall 白名单

镜像从 `mcr.microsoft.com` 拉。国内网络需要走镜像源，否则 Docker 会因为
配了不可达的代理而拉取失败。

内存较小的机器上注意：一个 Chromium 会话常驻 300-500 MiB。

## 数据来源

本插件通过王者营地的接口读取数据。腾讯没有开放面向第三方的玩家数据接口，
这里用的是营地客户端自己的接口。

营地账号可以设置战绩是否对外展示。对方关闭时查询会失败，插件会说明原因，
不做绕过。数据仅用于个人查询，请勿用于批量抓取。

## 开发

```sh
uv sync --group qq-verify   # 装依赖
uv run pytest
uv run ruff check .
```

协作约定见 [AGENTS.md](AGENTS.md)，更新日志见 [docs/CHANGELOG.md](docs/CHANGELOG.md)，
术语定义见 [docs/GLOSSARY.md](docs/GLOSSARY.md)。

## License

[WTFPL](LICENSE)