# 日常怎么用

> 你不需要背命令。只需要记住一句话：**每个 agent 开工时说"先按你的工作区指令走"。**

---

## 怎么启动一个"会接手"的会话

### 终端

```bash
am resume codex --exec       # 一条命令：进对目录 + 带上开场白
```

手动等价：

```bash
cd ~/your-project && codex
> 先跑 am brief --for codex，按第 2 段继续
```

### Cursor

你装了两个扩展：`anthropic.claude-code` 和 `openai.chatgpt`。
在面板里**新开一个会话**，把这条的输出粘进输入框：

```bash
am resume codex --prompt-only
```

输出就是开场白：

> 先运行 am brief --for codex。如果有多个任务在飞，把那张表原样贴给我，
> 等我指定继续哪个，不要自己挑；如果只有一个任务，就按第 2 段继续……

### 为什么开场白不能省

指令文件只告诉模型"有 am 这回事"，**新会话不一定会主动去读简报**——尤其你直接
打字问别的事时。一句开场白把它钉死，并且明确"多任务时先给我看表，别自己挑"。

### cwd 怎么影响

扩展的 cwd = Cursor 打开的那个文件夹。你现在开的是 `$HOME`，所以
`~/CLAUDE.md`（Claude Code）和 `~/AGENTS.md`（Codex）都会被加载——两处都有段落。
打开 `your project` 也一样，因为 `am` 靠 `~/.am-root` 指针定位库。

---

## 这些命令都是可选的

**只有 `am brief` 是必须的**——它是继任者自己的入口。其余都是可选的增量：

| 你做了 | 换来什么 |
|---|---|
| 什么都不做 | 继任者仍能看到转录里最后跑过的命令 |
| `am start <id>` | 这件事有了名字，能出现在多任务表格里 |
| \+ `am next "..."` | 继任者知道你**打算**做什么，而不是只能推断 |
| \+ `am log decision` | 后来的人不会悄悄推翻你的判断 |
| \+ `--accept` | 别人能在你不在时判断"算不算做完了" |

不知道什么时候算完成，就别写 `--accept`。简报会显示
`done when: not recorded（可选）`，这不是错误。

---

## 先看会话在干什么

**不需要先建任务。** `am brief` 在没有在飞任务时，直接列出最近的会话，每个会话三行：

```
### `dfc8985c` · claude-code · 静默 4 分钟 · FeatureEnhance

- 开始于：能不能把 static_bar 的配额算准一点
- 最近提问：ok，do your recommendations
- 推进到：watchdog 报 round 3 还在跑，正在评审 msb_volpeak/ambiguity
- 最后动作：`python3 -c "…watchdog/state.json…"`
  - **工作流** `sets3-hotstate` · failed · 推进到 3/5（Implement）· 静默 3 天 8 小时
  - 已通过：barsrc_book_retention, setbuild_narrowing_completeness, …
  - 被驳回：fb_change_legacy_fullmode_read
  - 无裁决（没跑完）：rolling_bar_history_state
    - rolling_bar_history_state 中断于：You've hit your weekly limit
  - **工件位置**（分支 @ head · 工作树）：
    - barsrc_book_retention · `wf6/barsrc_book_retention` @ a659928 · …/barsrc_book_retention/SequentialFeatureGraph-pubwt
    - msb_sortcut_blocked_sorted_window · `wf6/…` @ 66022b7 · …/SequentialFeatureGraph-private
  - fb_change_legacy_fullmode_read 被驳回，理由：Independent builds from git archives…
  - **下一步**：Integrate 及其之后的阶段都没走到
    **完成标准**（Integrate）：在 accel-sets3 分支上合并已接受的提交，构建 s3_all/s3_all_g，
    跑 FULL GATES vs REF 要求 0 差异；cachegrind 覆盖全部 10 个 set；state/name 覆盖 6 个；
    wall 用 5 次 ABAB 测 n_all/lts_n691/n129/n314
- 继续：`am adopt dfc8985c`
```

**如果会话是 Workflow 驱动的，会多出一段工作流摘要。** 它直接读
`<会话>/workflows/wf_*.json`：阶段走到哪、哪些 area 通过/驳回、为什么停的、
以及**到底还活着没有**（看文件 mtime，不看状态字段——那个可能三天没更新了）。

三段各自回答一个问题：

| 字段 | 来源 | 回答 |
|---|---|---|
| 标题 | agent 自己生成的会话名（Claude Code / DSH） | 它叫什么 |
| 开始于 | 会话的**第一条用户消息** | 当初为什么开这个会话 |
| 最近提问 | 最后一条用户消息 | 你后来又改了什么方向 |
| 推进到 | **最后一条助手长回复** | 现在做到哪了（agent 收尾时通常会总结） |
| 最后动作 | 转录里最后一条工具调用 | 停在哪个动作上 |

外加会话标题（Claude Code 和 DSH 自己会生成，如 `FeatureEnhance`、`反代`），
以及转录里最后一条命令作为兜底。

全部逐字取自转录，**不调用任何模型**。

选定后：

```bash
am adopt <会话id>        # 变成任务，并接管
```

单独看这张表：`am sessions`。

---

## 三个时刻

### 1. 开工

任何 agent 进来，第一件事就是读简报：

```bash
am brief --for claude-code      # 或 --for codex / --for dsh
```

**如果简报说"没有未完成的任务"**，而你现在确实要干活，先声明它：

```bash
am start <id> --accept "<怎么算做完>"
```

`am start` 一步做两件事：任务不存在就创建，然后把这个会话挂上去。
**必须在动手前做**——没注册的任务，对任何继任者都是不存在的。

五段：目标 · 当前任务+验收判据 · 最近事件与机器观测 · **下一步的精确命令** ·
阻塞项与不可推翻的决策。

如果第 2 段写着租约在别的 agent 手上，而那个 agent 已经挂了或没额度：

```bash
am claim <task-id> --force
```

### 2. 干活中

只在"值得被记住"的时候记一条，不要记流水账——**你的命令已经被转录自动抓走了**。

```bash
am log decision "为什么这么做" --task <id>
am log result  "现在什么可用了" --task <id> --evidence "pytest ... → 12 passed"
```

### 3. 收工 / 额度快没了

```bash
am next "<你本来要跑的下一条命令>" --task <id>
```

**这一条最关键。** 其余信息（今天改了哪些文件、跑了什么、卡在哪）转录里都有，
唯独"接下来想干什么"只有你知道。

---

## 换 agent（核心场景）

Claude 额度用完，直接在同一个目录起 codex：

```bash
cd ~/your-project
codex
> 接着干
```

Codex 会自己跑 `am brief --for codex`，看到租约在 `claude-code` 手上，
自己 `am claim <id> --force` 接手。**不用你告诉它任务 ID。**

额度恢复后回到 Claude：

```bash
am brief --for claude-code
```

第 3 段的"最近事件"里就是 codex 干过的事，第 4 段是它留下的下一步。

---

## 多个会话并行时（你的常态）

你同时开 3-5 个 Claude 会话跑不同任务时，`am brief` 不显示单个任务，而是**一张表**：

```
| id        | status  | agent       | session       | quiet   | last action      |
| feat-imb  | claimed | claude-code | fffbbe58-9ad0 | 12m     | pytest tests/... |
| mig-dl2   | claimed | claude-code | dfc8985c-4111 | **18m** | python -m mig... |
| study-ewap| claimed | claude-code | 5a525274-9edc | **94m** | 读 doc/ewap.md   |
```

`quiet` = 那个会话多少分钟没写转录了。**加粗 = 超过 15 分钟没动静，基本是死了或没额度。**

于是你有两个选择：

```bash
am brief --task mig-dl2          # 只展开这一个
am claim mig-dl2 --force         # 直接接管
```

或者在 codex 里直接说"接着干 mig-dl2 那个"，它会照做。

**为什么不让它自己猜**：五个会话里哪个该续，取决于你此刻想干什么，磁盘上的证据
只能告诉你"谁还活着、谁停在哪一步"。所以系统给证据，决定权留给你。

同一个 agent 的另一个会话想抢已被占用的任务会被拒，报错里会写清是哪个会话、静默多久：

```
am: task 'feat-imb' is held by claude-code / fffbbe58-9ad0..., last active 12m ago
```

---

## 面板

```bash
am serve                     # http://127.0.0.1:37778/
am serve --host 0.0.0.0      # 局域网
```

**左侧是导航，右侧是内容**，每 2.5 秒自动刷新，且内容没变时完全不重绘。

### 左侧：分组会话列表

顶上是**搜索框**，按 agent 分组（claude-code / codex / dsh），点分组标题折叠。

**默认显示最近 30 天内的全部会话**（不是固定条数）。改窗口：

```bash
# .agents/config.json
{"dashboard_days": 30}
```

**subagent 转录不算会话**——它们挂在 `<会话>/subagents/` 下，数量是真人会话的几十倍
（当前 1250 个），会淹没列表，已经排除。

每条一行，名称**有标题用标题 → 没有就用"推进到"那句 → 再没有才显示 id**：

```
● FeatureEnhance            wf 3/5     ← 绿点=活着；wf 3/5=工作流进度
○ Migration                 wf 3/3
○ 已修复：DeepSeek 未信任公网…      2h
```

**当前主 agent 那条加粗**。底部「已隐藏 N 展开」。

### 右侧：概览或详情

**概览**：四个数字（活跃会话 / 在飞任务 / 最近会话 / 工作流）+ 当前主 agent + 在飞任务 + 工作流状态。
任务里的会话 id 可以**直接点进去**。

**详情**：标题、agent、会话 id、静默时长、开始于 / 最近提问 / 推进到 / 最后动作、工作流阶段步进器。
顶部三个按钮：**复制 `am adopt`**、**复制 `am brief --for <agent>`**、**隐藏这个会话**。

### 快捷键

| 键 | 作用 |
|---|---|
| `/` | 聚焦搜索框 |
| `↑` `↓` | 在会话间移动 |
| `Esc` | 搜索框里清空；否则回到概览 |
| `p` | 暂停/恢复自动刷新（读长文时用） |

搜索匹配会话 id、agent、标题、开始于、最近提问、推进到、最后动作、工作流名。

### 藏掉没用的会话

有些会话开了就死，什么都没留下（比如 `7a8feaff`）。它们不归 `am` 管、删不掉，
但可以让它们不再出现：

```bash
am hide 7a8feaff --reason "空会话"
am hide 7a8feaff --undo          # 恢复
am prune --sessions              # 自动找出所有空会话（试运行）
am prune --sessions --yes        # 真的藏起来
```

被隐藏的会话在面板和 `am sessions` 里都不再出现，但转录文件原封不动。
想找回来：面板底部「已隐藏 → 展开」，或者 `am hide <id> --undo`。

---

## 找东西

```bash
am recall "截断测试"                    # 精确词，~2 秒
am recall "忘了当时怎么定的" --smart     # 语义，~12 秒
am recall "static_bar" --agent codex     # 只搜某个 agent
```

---

## 清理与归档

先看清什么在长（实测）：

| 部分 | 体积 | 会无限长吗 |
|---|---|---|
| `idx/` 向量索引 | ~40 MB | 不会，30 天滑窗，且**可重建** |
| `tail/` 观测 | ~1 MB | 不会，每 agent 400 行轮转 |
| `journal/` | ~2 MB/年 | 慢，但不可重建 |
| `tasks/` | 1 KB/个 | 会，done 任务堆积 |

**真正会长的是转录目录（1.5 GB）——那不是 `am` 的，不要用 `am` 去删。** 清转录是 Claude Code / Codex 自己的事（`/clear` 或删旧项目目录），`am` 只是读它们。

### 两个命令

```bash
am task list          # 默认只看未完成
am task list --all    # 含已完成

am prune              # 试运行，先看要归档什么
am prune --yes        # 真正归档
am prune --days 180   # 改保留期
```

`am prune` 会先打印**库里各部分占多少**，再列出要归档的项。**默认是试运行**，不加 `--yes` 不动任何文件。

### 归档到哪

`archive/` 下按月分片：

| 类型 | 形式 |
|---|---|
| 已完成任务 | `archive/tasks/tasks-2026-07.jsonl.gz`，一行一个 JSON |
| 旧 journal | `archive/journal/codex-20260601.jsonl.gz` |
| 旧简报 | `archive/briefs/<name>.md`（明文，方便直接看） |

gzip 支持追加成员，所以归档只追加、从不重写。

### 一条规则

**不删无法重建的东西。** 转录不碰；journal 和已完成任务是不可重建的，所以压缩归档而不是删除；`idx` 和 `tail` 本来就有界，不用管。

---

## 体检

```bash
am status     # 任务表 + 最近观测
am doctor     # 交接是否就绪（exit 1 = 有问题）
am where      # 库在哪
```

---

## 三个 agent 的入口

| agent | 从 `~` 启动时读的指令文件 |
|---|---|
| claude-code | `~/CLAUDE.md` |
| codex | `~/AGENTS.md` |
| dsh | `~/AGENTS.md` + `~/your-project/AGENTS.md` |

四份文件里是同一段 `<!-- am:entry -->`。改一处就要同步四处（或用
`~/.agents` 那种软链——但软链会让 Codex 的沙箱直接拒绝执行，见 DESIGN.md）。

---

## 不要做的事

- **不要手改** `state.md` 和 `journal/*.jsonl`。前者是编译产物，后者是审计日志。
- **不要把密钥写进命令行**。转录抓取会把命令原样复制进 `tail/`。
- 不要指望 `claude --continue` / `codex resume` 跨模型生效——它们只能续自己的会话。
  跨模型接力的载体是磁盘上的 journal，不是会话。

---

## 出问题时

| 现象 | 看哪里 |
|---|---|
| agent 不知道有这回事 | 它的指令文件里有没有 `am:entry`（`am doctor` 会查） |
| `am: no .agents/ store found` | `~/.am-root` 指向对不对；或 `cd` 回仓库 |
| 简报第 2 段说"没有待办" | 任务真的都关了，先 `am status` 确认 |
| `--smart` 报错 | 它会自动退回字面搜索，不影响使用 |
