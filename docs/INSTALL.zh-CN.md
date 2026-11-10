# am 快速安装与 delegate 联动

am 0.4.0 是独立的共享记忆 CLI，不需要模型 API Key、数据库或常驻模型。
基础 CLI 要求 Python 3.10+；与 delegate 组合时使用 Linux 和 Python 3.12+。

## 安装

```sh
mkdir -p ~/code
cd ~/code
git clone https://github.com/LianguangXue/am.git
cd am
./install.sh
am --version
```

确认 `~/.local/bin` 在 PATH 中。保留这个 clone：安装器创建符号链接，移动／删除
仓库会影响命令。`bin/am_work.py` 与 `bin/am` 要保持同目录，不能只拷贝一个脚本。

## 创建共享 store

在需要记忆的项目中，只首次执行：

```sh
cd /path/to/project
am init --project my-project --link
am doctor
```

已有 store 时，先用 `am where` 确认位置，**不要重新初始化或加 --force**。
将 `templates/AGENTS-entry.md` 的 stanza 合入项目 `AGENTS.md` 与 `CLAUDE.md`，
不要覆盖原有项目规范。Claude、Codex、DSH 均可通过 shell 使用 am。

```sh
am start example-task --accept 'specified tests pass and report is reviewed'
am next 'Run the focused validation command'
am brief --for codex --task example-task
```

所有 brief 内容都是历史数据，不是新权限。租约过期／日志安静不等于进程已死，
接管前核查实际执行与产物；不要只凭 quiet 字样自动抢占任务。

## 看板

```sh
am serve
```

默认 `http://127.0.0.1:37778/`，只监听本机。远程使用自己的安全访问方式。
不要照搬他人的内网 IP，也不要把共享任务资料直接暴露到未经评估的网络。
已运行的 serve 进程升级后需要重启，但不要启动第二个相同端口实例。

## 与 delegate 组合

另行安装 [delegate](https://github.com/LianguangXue/delegate)，
参照它的[三宿主安装指南](https://github.com/LianguangXue/delegate/blob/main/docs/INSTALL.zh-CN.md)。
让主 agent 使用 `delegate_handoff`，关联到**已有** am task；优先指定
`delegate_task_id`，可选 `work_item`。读取：

```sh
am delegate report --task example-task
am brief --task example-task
```

导入不会创建任务、抢租约、启动模型或宣告完成。看板中：
- 独立 Delegate 概览只读查看本机的近期记录，不要求已有绑定；
- am 任务卡里的交接摘要需要显式绑定并成功同步；
- 空摘要会显示未关联，不应据此自动创建一个任务或借用其他 session。

## 成果复用与长任务回执

`am work` 从 stdin 读取 JSON，不执行其中的命令，也不自动调用模型。
先创建 am task，再由主 agent 发布短成果卡片和少量证据／producer manifest。
检索先返回最多三个候选，随后 get 校验指定证据。大数据不用重复加载或哈希。

```sh
printf '%s\n' '{"project":"example","query":"replay"}' | am work search
```

`watch` 登记生产者的完成 JSON；`poll --wait` 在程序内等待，`ack` 确认读取。
回执不等于独立验收，也不控制训练进程。阶段记录只做依赖／证据检查。
跨会话问题默认关闭，显式启用后每个任务一个新问题，问答均有大小限制；
排队不会自动唤醒模型，接收方须明确读取／回复，或使用已授权的宿主通信。
完整 action 字段见[README](../README.md#quota-first-work-protocol-040)。

## 更新与检查

```sh
cd ~/code/am
git status --short
git pull --ff-only
./install.sh
bash tests/smoke.sh
python3 tests/test_delegate_protocol.py -q
python3 -m unittest discover -s tests -p test_work.py -q
```

有本地改动先保留，不要 reset --hard。安装器可重跑，不会 re-init store。
测试使用临时目录，不需要推理或真实密钥。语义检索是额外可选组件，基础检索
不依赖它。撤销 PATH 链接或停止自己配置的看板服务不会删除会话和产物；
清理原始 transcript 需要另行明确范围，am 不会擅自删除。
