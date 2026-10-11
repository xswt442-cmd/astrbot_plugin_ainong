# 发版

一次发版是升一个版本号、合并到 `main`、在合并后的提交上打 `vX.Y.Z` 标签。
分支推送不发布任何东西。示例用 `dev`，换别的开发分支同理。

## 一次发版会影响什么

- **GitHub Release** —— 第 6、7 步手动触发，不自动。打标签和建 Release 是两步，
  都要做。
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
   - `docs/CHANGELOG.md` 的首个小节，标题写成 `## [X.Y.Z] - YYYY-MM-DD`

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

6. 在 `main` 上打标签并推送：

   ```sh
   git tag vX.Y.Z main
   git push origin vX.Y.Z
   ```

   **在 `tag` 命令里写 `main`，不要给 `HEAD` 所在的位置打标签。** 这是
   squash 或 rebase 合并会踩的坑：分支上的提交会被替换成 `main` 上的一个新提交，
   在分支提交上打的标签从 `main` 不可达，市场和 GitHub 拿到的就不是同一份代码。
   如果已经打错了，本地删掉这个标签，合并完再打 `main`。

7. 建 GitHub Release。**`git tag` 推上去不等于有 Release** —— 标签只是给某个
   提交起了个名字，Release 是另一个对象，要在 Releases 页面才看得见。少做这
   一步，`git tag` 成功了但 Releases 页面仍是旧的，很容易以为已经发完。

   ```sh
   gh release create vX.Y.Z --title "vX.Y.Z" --notes "<CHANGELOG 对应小节>"
   ```

   说明直接取 `docs/CHANGELOG.md` 对应小节的内容。发完核对一次：

   ```sh
   gh release list
   ```

   最新的那条要显示为 `Latest`，且版本号是刚发的那个。

8. 要进 AstrBot 插件市场，开 <https://cloud.astrbot.app/publish>，填本仓库地址
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
   | `support_platforms` | 可选，`aiocqhttp` 与 `weixin_oc` |
   | `tags` | 可选，用于市场分类搜索 |
   | `social_link` | 可选，GitHub 主页 |

   `short_desc` 也在 `metadata.yaml` 里，界面紧凑时会显示它——一句话，别把
   `desc` 塞进去。

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
