# 发版

一次发版是升一个版本号、合并到 `main`，然后在 Actions 里触发 `release`
工作流，它会打标签并建 Release。

**不要本地打标签。** 标签和 Release 是两个对象，分开手做会漏——v0.1.2 与
v0.1.3 就只推了标签，Releases 页面停在 v0.1.1。

分支推送不发布任何东西。示例用 `dev`，换别的开发分支同理。

## 一次发版会影响什么

- **GitHub Release** —— 手动触发 `release` 工作流，不自动。
- **AstrBot 插件市场** —— **不由标签驱动**。要在
  <https://cloud.astrbot.app/publish> 发布，注册 AstrBot Cloud 账号后填本仓库
  地址，平台自己解析 `metadata.yaml`。

  老的 [`AstrBot_Plugins_Collection`](https://github.com/AstrBotDevs/AstrBot_Plugins_Collection)
  仓库已标注 `DEPRECATED`，README 明确写着「请直接提交到新平台」，不要再去那里提 PR。

  平台会校验压缩包体积**不超过 16 MB**，超了直接拒绝发布。本仓库的 zip 远小于
  这个限制，但改动后值得看一眼——尤其是新增图片或音频资源时。

  两条约定：

  - **文件名必须是 `logo.png`。** 这由 AstrBot 硬编码（`star_manager.py` 里的
    `logo_fname`），改名就不显示。本地装插件和市场上架走的是两套逻辑，但
    文件名要求一样。
  - **发版必须合到 `main`。** 平台从 GitHub 仓库取包，`dev` 分支上的东西
    不会被打进 zip。

## 清单

1. 在开发分支上定 `X.Y.Z`，更新带版本的地方：

   - `metadata.yaml` 的 `version`（带 `v` 前缀，如 `v0.1.0`）
   - `pyproject.toml` 的 `version`（**不带** `v`，如 `0.1.0`）
   - `docs/CHANGELOG.md` 的首个小节，标题写成 `## [X.Y.Z] - YYYY-MM-DD`

   三处都要改。`test/test_version.py` 会检查它们一致，CI 每次推送都跑。

2. 跑本仓库的检查（命令见 `AGENTS.md` 的验证一节）：

   ```sh
   uv run pytest
   uv run ruff check .
   uv run ruff format --check .
   ```

3. 提交并推开发分支：

   ```sh
   git commit -am "chore: release X.Y.Z"
   git push origin dev
   ```

4. 等这个分支的 CI 变绿。此时**什么都没发布**——标签不存在，CI 只验证。

5. 合并到 `main` 并推送：

   ```sh
   git switch main
   git pull
   git merge --no-ff dev -m "merge: dev -> main"
   git push origin main
   ```

6. 在 Actions 里触发 `release` 工作流：<https://github.com/xswt442-cmd/astrbot_plugin_ainong/actions/workflows/release.yml>
   → Run workflow → 填版本号（带 `v`，如 `v0.1.4`）。

   工作流会自己完成剩下的事，并在每一步前先检查：

   - 触发的是 `main` 而不是别的分支
   - 版本号格式是 `vX.Y.Z`
   - `metadata.yaml`、`pyproject.toml`、`docs/CHANGELOG.md` 三处版本号一致
   - `main` 的 CI 是绿的（最多等 10 分钟）
   - 这个标签还没被占用
   - `git archive` 出来的包里没有 `test/` 和 `.github/`，有 `logo.png`，且不超过 16 MB

   然后打标签（显式写 `main`，不给 `HEAD` 所在位置打标签——squash 或 rebase
   合并会把分支提交换成 `main` 上的新提交，在分支提交上打的标签从 `main`
   不可达，市场和 GitHub 拿到的就不是同一份代码），再建 Release，说明自动
   取 `CHANGELOG` 对应小节。最后核对最新的 Release 是 `Latest` 且版本号正确。

   工作流跑完后，**市场发布还没做**，继续第 7 步。

7. 要进 AstrBot 插件市场，开 <https://cloud.astrbot.app/publish>，填本仓库地址
   提交。平台自己解析 `metadata.yaml`，所以这些字段要写对：

   | 字段 | 值 |
   |---|---|
   | `name` | `astrbot_plugin_ainong`，英文唯一，改了等于换插件 |
   | `display_name` | 爱农 |
   | `desc` | 详细描述，支持多行 Markdown |
   | `version` | 与 `metadata.yaml` 一致，如 `v0.1.0` |
   | `author` | xswt442-cmd |
   | `repo` | https://github.com/xswt442-cmd/astrbot_plugin_ainong |
   | `astrbot_version` | 可选，`>=4.16,<5` |
   | `category` | 市场分类，只能填市场那九个中文之一，见下 |
   | `tags` | 可选，列表。用于市场分类搜索 |
   | `support_platforms` | 可选，`aiocqhttp` 与 `weixin_oc` |
   | `social_link` | 可选，GitHub 主页 |

   `short_desc` 也在 `metadata.yaml` 里，界面紧凑时会显示它——一句话，别把
   `desc` 塞进去。

   **分类只能是这九个**：`其他`、`工具`、`娱乐`、`三方集成`、`生活`、
   `长期记忆`、`知识库`、`AI 增强`、`语音`。填错或漏填都不会让安装失败，
   只会归到「其他」、在详情页显示成 `[MISSING: ...其他]`，而且要等市场索引
   刷新才看得到。`test/test_metadata.py` 会校验，别绕开它。

## 标签发布后能改吗

不能。同一个标签指向的提交是既定的。想修正就发一个新版本，旧版本留着。

如果某个版本有问题而内容本身没错，改 `metadata.yaml` 里的版本号是不够的——
已经装出去的插件不会因为版本号变化而更新。要让用户拿到修正，发新的补丁版本。

## 发版前值得确认的两件事

这两个问题在发版前发现代价很小，发出去之后再改就要发新版本：

- **打出来的包会包含什么。** 平台从 `main` 拉 zip。想确认内容就在本地
  `git archive` 一次看看，别等发出去才发现包里带了不该带的东西。
  `requirements.txt` 和 `pyproject.toml` 也要同步——CI 有这道检查，但装插件
  用的是前者，不同步会让用户装到缺包的版本，而开发环境一切正常。
