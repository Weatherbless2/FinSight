# Codex 中 speedy 与 cherry 的会话保留和切换指南

## 1. 先说明当前状态

当前会话数据没有通过“把旧会话复制成新会话”的方式迁移。历史会话仍保留在原来的本地会话文件中，标题、消息顺序、代码和附件引用都不应该被改写。

当前配置采用了一个兼容层：

```text
新建会话默认使用 cherry
历史会话仍可能记录 provider = speedy
speedy 这个配置键保留，用来让历史会话可以被识别
speedy 兼容键当前指向 cherry 网关
```

这样做的目的，是让旧 speedy 会话的原文内容继续保留，同时避免继续请求已经返回 `401 INVALID_API_KEY` 的旧 `speedyapi.best` 端点。

## 1.1 本次问题的实际修复过程

本次故障的完整链路如下：

```text
原配置使用 speedy
        ↓
切换到 cherry 时删除了 speedy 配置段
        ↓
左侧索引仍能显示历史标题
        ↓
历史会话记录仍保存 provider = speedy
        ↓
应用最初无法识别 speedy，历史正文打不开
        ↓
恢复 speedy 配置后，历史正文可以打开
        ↓
继续会话时仍请求旧 speedyapi.best
        ↓
旧 API key 无效，返回 401 INVALID_API_KEY
        ↓
把 speedy 保留为兼容键，但将其 base_url 指向 cherry
        ↓
完全重启 Codex，使运行中的进程重新读取配置
        ↓
旧 speedy 会话保留原文，并通过 cherry 网关继续使用
```

本次实际采用的最终配置关系是：

```toml
model_provider = "cherry"

[model_providers.cherry]
name = "cherry"
base_url = "https://gptch.cloud/v1"
wire_api = "responses"
requires_openai_auth = true

[model_providers.speedy]
name = "speedy"
base_url = "https://gptch.cloud/v1"
wire_api = "responses"
requires_openai_auth = true
```

这里的 `speedy` 不是被删除，也不是把历史消息复制成了新会话，而是作为历史会话的兼容 provider key 保留下来。旧会话中的 `provider = speedy` 因此可以被识别，同时请求实际走 cherry 网关。

本次验证确认：

- `config.toml` 可以正常解析；
- 默认供应商为 `cherry`；
- `cherry` 和 `speedy` 两个 provider key 都存在；
- 历史会话文件数量没有减少；
- 历史消息正文没有批量重写；
- 修改前的配置、会话、SQLite 和附件均已备份；
- 重启后旧会话可以继续使用；
- 继续会话时不再请求失效的 `speedyapi.best`。

## 1.2 为什么一定要重启 Codex

只修改磁盘上的 `config.toml` 不一定会立即改变已经运行的 Codex 进程。运行中的进程可能已经把 provider 配置加载到内存中，因此即使文件里的 `speedy.base_url` 已经改成 cherry，当前进程仍可能继续请求：

```text
https://www.speedyapi.best/responses
```

正确顺序是：

1. 先备份；
2. 修改 `config.toml`；
3. 停止当前生成任务；
4. 完全退出 Codex；
5. 重新打开 Codex；
6. 再打开旧会话并继续生成；
7. 检查错误或请求地址是否已经变成 `https://gptch.cloud/v1`。

如果没有重启，不能根据磁盘配置判断运行时已经切换成功。

## 2. 必须遵守的原则

1. 始终同时保留 `[model_providers.speedy]` 和 `[model_providers.cherry]` 两个配置段。
2. 不要删除或重建 `sessions` 目录。
3. 不要清空 `session_index.jsonl`。
4. 不要把所有历史 JSONL 文件直接删除后重新导入。
5. 每次修改配置或会话文件前，先退出 Codex 桌面应用，并完成备份。
6. 不要把 API key 写入本文件、截图、聊天消息或 Git 仓库。
7. 切换供应商只修改配置，不修改历史消息正文。

## 3. 重要目录

默认数据目录：

```text
C:\Users\weath\.codex
```

重点文件和目录：

```text
C:\Users\weath\.codex\config.toml
C:\Users\weath\.codex\session_index.jsonl
C:\Users\weath\.codex\sessions\
C:\Users\weath\.codex\sqlite\
C:\Users\weath\.codex\attachments\
```

其中：

- `config.toml` 决定供应商名称、地址和默认供应商；
- `sessions` 保存会话事件和消息正文；
- `session_index.jsonl` 保存左侧会话列表需要的索引信息；
- `sqlite` 保存本地目录、时间线和其他应用状态；
- `attachments` 保存会话附件或附件索引相关文件。

### 3.1 WSL 端对应路径

如果当前是在 WSL 中运行 Codex，Windows 路径应替换为下面的 Linux 路径：

```text
/root/.codex/config.toml
/root/.codex/session_index.jsonl
/root/.codex/sessions/
/root/.codex/state_5.sqlite
/root/.codex/thread_history_1.sqlite
/root/.codex/attachments/
```

WSL 窗口的本地历史列表默认会按当前工作目录筛选。若要让从 Windows 客户端导入的历史会话在 WSL 当前窗口中直接显示，必须把 WSL `state_5.sqlite` 中这些历史线程的 `cwd` 设为当前 WSL 工作目录（例如 `/root/projects/TradingAgents`）。这只修改列表索引元数据，不修改 provider、会话 ID、rollout JSONL、消息正文或附件。

## 4. 每次切换前的备份流程

先完全退出 Codex 桌面应用，确认任务栏和进程中不再有正在运行的 Codex 桌面进程。然后在 PowerShell 中执行下面的命令：

```powershell
$codexRoot = 'C:\Users\weath\.codex'
$backupRoot = 'C:\Users\weath\Documents\Codex\speed-switch-backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss')

New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $codexRoot 'config.toml') -Destination $backupRoot
Copy-Item -LiteralPath (Join-Path $codexRoot 'session_index.jsonl') -Destination $backupRoot
Copy-Item -LiteralPath (Join-Path $codexRoot 'sessions') -Destination $backupRoot -Recurse
Copy-Item -LiteralPath (Join-Path $codexRoot 'sqlite') -Destination $backupRoot -Recurse
Copy-Item -LiteralPath (Join-Path $codexRoot 'attachments') -Destination $backupRoot -Recurse

Get-ChildItem -LiteralPath $backupRoot -Recurse -File |
    Measure-Object -Property Length -Sum
```

备份目录中的文件数量和总大小应当大于零。不要在备份未完成时修改配置。

## 5. 当前推荐模式：使用 cherry，同时保留旧 speedy 会话

这是日常推荐状态。配置逻辑应当类似下面这样：

```toml
model_provider = "cherry"

[model_providers.cherry]
name = "cherry"
base_url = "https://gptch.cloud/v1"
wire_api = "responses"
requires_openai_auth = true

# Compatibility alias for historical sessions that store provider = speedy.
# It intentionally routes those sessions to the current cherry gateway.
[model_providers.speedy]
name = "speedy"
base_url = "https://gptch.cloud/v1"
wire_api = "responses"
requires_openai_auth = true
```

在这个模式下：

- 新建会话默认走 `cherry`；
- 旧会话即使保存了 `provider = speedy`，也能找到对应配置；
- 旧会话继续生成时实际请求走 `cherry` 网关；
- 原来的旧消息不会被改写；
- `cherry` 新增加的会话继续保留并正常打开。

如果截图中的错误是：

```text
401 INVALID_API_KEY
https://www.speedyapi.best/responses
```

说明兼容别名没有生效，或者应用还没有重新读取配置。此时先确认 `speedy` 段的 `base_url` 是 `https://gptch.cloud/v1`，再完全退出并重新打开 Codex。

## 6. 以后切换到真实 speedy

如果以后重新获得了有效的 speedy API key，并且确实要让新请求走旧 speedy 网关，按下面的顺序操作。

### 6.1 保留 cherry 配置

不要删除这一段：

```toml
[model_providers.cherry]
name = "cherry"
base_url = "https://gptch.cloud/v1"
wire_api = "responses"
requires_openai_auth = true
```

保留它，才能让当前已经由 cherry 创建的会话继续打开。

### 6.2 把 speedy 兼容别名改回真实 speedy

```toml
model_provider = "speedy"

[model_providers.speedy]
name = "speedy"
base_url = "https://www.speedyapi.best/"
wire_api = "responses"
requires_openai_auth = true
```

`model_provider = "speedy"` 只影响新建会话的默认选择，不会删除或改写已有 cherry 会话。

### 6.3 供应商切换后的会话关系

```text
旧 speedy 会话  -> 继续引用 speedy
旧 cherry 会话  -> 继续引用 cherry
新建会话        -> 默认引用 speedy
```

因此，切换到真实 speedy 后，左侧两类历史记录可以同时保留。

如果旧 speedy API key 仍然无效，旧 speedy 会话在继续生成时仍会收到 401。此时不要删除会话；把 `speedy` 的 `base_url` 临时恢复为 cherry 网关即可读取和继续使用这些历史会话。

## 7. 切回 cherry

切回时同样先备份，然后将默认供应商和兼容别名恢复为：

```toml
model_provider = "cherry"

[model_providers.cherry]
name = "cherry"
base_url = "https://gptch.cloud/v1"
wire_api = "responses"
requires_openai_auth = true

[model_providers.speedy]
name = "speedy"
base_url = "https://gptch.cloud/v1"
wire_api = "responses"
requires_openai_auth = true
```

切回后：

- cherry 会话继续走 cherry；
- 历史 speedy 会话通过兼容键走 cherry；
- 所有历史正文仍然保留；
- 不需要批量替换 JSONL 中的消息内容；
- 不需要清空 SQLite 数据库。

## 8. 切换后的验证清单

每次重新打开 Codex 后，按以下顺序检查：

1. 新建一个短会话，确认默认供应商是目标供应商。
2. 打开一个旧 speedy 会话，确认首条、中间几轮和最后一条消息都存在。
3. 打开一个已有 cherry 会话，确认其内容没有变化。
4. 打开一个包含代码块的会话，确认代码没有截断。
5. 打开一个包含附件引用的会话，确认附件仍然可见。
6. 发送一条测试消息，确认请求地址不是错误的旧地址。
7. 如果出现 401，先看错误中的 URL，再检查对应 provider 的 `base_url`。
8. 不要用“左侧标题还在”作为完整恢复依据，必须实际打开并读取正文。

## 9. 看到错误时如何判断

### `Model provider "speedy" not found`

说明 `config.toml` 中缺少 `[model_providers.speedy]`。恢复该配置段，不要改数据库。

### `401 INVALID_API_KEY` 且 URL 是 speedyapi.best

说明请求仍然走真实 speedy，但 key 无效。若目标是使用 cherry，把 speedy 兼容别名的地址改为 `https://gptch.cloud/v1`。

### `401 INVALID_API_KEY` 且 URL 是 gptch.cloud

说明 cherry 当前认证也无效，需要在应用允许的认证入口更新认证；不要把 key 写进配置文档或会话内容。

### 会话标题存在但正文打不开

先检查 provider 配置是否存在，再检查 `sessions` 目录和 `session_index.jsonl`，不要先清缓存或重建数据库。

### 配置文件已经改了，但错误 URL 仍然没有变化

Codex 桌面进程会在启动或创建运行时会话时读取供应商配置，已经运行的进程可能继续使用内存中的旧配置。修改磁盘上的 `config.toml` 不一定会热更新当前会话。

处理顺序：

1. 先停止当前会话的生成任务；
2. 完全退出 Codex 桌面应用；
3. 确认 Codex 进程已经退出；
4. 重新打开 Codex；
5. 再打开旧会话并检查错误中的 URL。

如果错误 URL 仍然是 `https://www.speedyapi.best/`，不要继续点击“继续”反复重试。再次确认当前 `config.toml` 中的 `speedy.base_url`，并确认重新启动的是同一个 Codex 数据目录。

不要在会话仍有写锁时直接批量改写 `sessions` 下的 JSONL 文件。写锁存在时，应用可能在稍后把内存中的旧设置写回磁盘，覆盖人工修改。

## 10. 回滚

如果切换后出现异常：

1. 退出 Codex；
2. 保存错误截图和日志；
3. 用最近一次备份中的 `config.toml` 恢复配置；
4. 不删除当前 `sessions`、`sqlite` 或 `attachments`；
5. 重新打开 Codex；
6. 抽查一个旧 speedy 会话和一个新 cherry 会话。

只有在确认数据库文件被实际覆盖或损坏时，才考虑从完整备份恢复数据目录。配置问题优先只回滚 `config.toml`。

## 11. 最终目标状态

```text
speedy 历史会话正文       保留
cherry 新会话正文         保留
speedy 配置键             保留
cherry 配置段             保留
默认新会话供应商           按当前需要选择
切换时的备份               每次执行
数据库和消息正文           不做批量改写
```

最重要的一点是：供应商切换是配置层操作，会话内容是数据层内容。只要两个 provider 配置段都保留、切换前完成备份、不开启批量重写历史 JSONL，就可以在保留两类历史记录的前提下往返切换。

## 12. 下次切换到真实 speedy 的实际操作步骤

下面是以后可以直接照做的版本。

### 第一步：停止使用中的会话并退出 Codex

先停止生成任务，然后完全退出 Codex。不要在应用仍然打开、会话仍然有写锁时直接修改 `config.toml` 或 `sessions` 文件。

### 第二步：创建本次切换备份

执行第 4 节的备份命令。每次切换都使用新的时间戳目录，不要覆盖之前的备份。

### 第三步：保留 cherry 配置

不要删除 `[model_providers.cherry]`。它是当前 cherry 会话能够继续打开的必要配置。

### 第四步：把 speedy 兼容地址改回真实 speedy

```toml
model_provider = "speedy"

[model_providers.cherry]
name = "cherry"
base_url = "https://gptch.cloud/v1"
wire_api = "responses"
requires_openai_auth = true

[model_providers.speedy]
name = "speedy"
base_url = "https://www.speedyapi.best/"
wire_api = "responses"
requires_openai_auth = true
```

这一步只改变默认新会话和旧 speedy 会话的请求地址，不会删除 cherry 会话。旧 cherry 会话仍然通过 `[model_providers.cherry]` 访问 cherry。

### 第五步：重新启动 Codex

必须完全退出后重新打开。只关闭当前会话、只切换左侧页面或只点击“继续”，都不能保证 provider 配置已经重新加载。

### 第六步：验证两类会话

至少检查：

```text
一个旧 speedy 会话       -> 能打开、能继续
一个当前 cherry 会话     -> 能打开、能继续
一个新建会话             -> 默认使用 speedy
```

同时检查错误中的 URL。真实 speedy 模式下，旧 speedy 和新 speedy 会话应请求 `speedyapi.best`；已有 cherry 会话仍应请求 `gptch.cloud`。

### 第七步：如果 speedy 返回 401

这表示 speedy 地址已经生效，但 speedy API key 无效或过期。此时不要删除任何历史会话。将 `speedy.base_url` 临时改回：

```toml
base_url = "https://gptch.cloud/v1"
```

然后重启 Codex，恢复为本文件第 5 节的 cherry 兼容模式。

## 13. 下次切回 cherry 的实际操作步骤

1. 停止生成任务并退出 Codex；
2. 创建新的切换备份；
3. 设置 `model_provider = "cherry"`；
4. 保留 `[model_providers.cherry]`；
5. 将 `[model_providers.speedy].base_url` 设置为 `https://gptch.cloud/v1`；
6. 重新启动 Codex；
7. 打开一个旧 speedy 会话和一个 cherry 会话分别测试；
8. 确认请求地址已经是 `https://gptch.cloud/v1`。

不要为了切换供应商批量修改消息正文，也不要删除旧 speedy provider key。只要 provider key 和对应地址都保留，历史会话就能继续被识别。

## 14. 一次性双端恢复客户端与 WSL 历史会话

本节解决的是一次性恢复当前已有的历史会话，不是持续同步功能。

目标状态：Windows 客户端和 WSL 都能看到同一份历史会话集合；会话标题按最初创建环境标识来源：

```text
<客户端> 原客户端会话标题
<wsl>    原 WSL 会话标题
```

两个会话根目录为：

```text
客户端：C:\Users\weath\.codex
WSL：/root/.codex
```

### 14.1 可安全合并的数据

以下数据是历史会话恢复的核心，必须按会话 ID 增量合并：

- `sessions/`：会话 JSONL 正文和事件；
- `session_index.jsonl`：左侧会话列表和标题；
- `attachments/`：会话附件和附件清单。

历史消息正文、事件顺序、代码块、附件内容和会话 ID 不应被重写。标题只增加一次 `<客户端>` 或 `<wsl>` 前缀。

不要复制或合并以下环境专属文件：

- `auth.json`；
- `config.toml`；
- `logs_2.sqlite`、`queue_1.sqlite`、`memories_1.sqlite`、`goals_1.sqlite`。

两端各自保留认证与配置；两边的 `cherry` 和 `speedy` provider 配置段仍必须存在。

### 14.2 SQLite 和运行中会话

`state_5.sqlite` 与 `thread_history_1.sqlite` 是本地历史投影，可能伴随 `-wal` 和 `-shm` 文件。Codex 正在运行时，绝不能直接覆盖、拼接或从另一端复制这两个数据库。

正确顺序：

1. 两端 Codex 都完全退出；
2. 备份两端的 `sessions`、索引、附件和 SQLite；
3. 合并可移植的 JSONL、索引和附件；
4. 重启各端 Codex，让它从统一后的会话源文件建立或更新本地历史投影；
5. 逐条实际打开会话验证，不以左侧标题存在作为唯一依据。

如果合并期间有会话仍在继续生成，两个同 ID 的 JSONL 文件可能长度不同。此时不能自动覆盖任一端，应在该会话结束且 Codex 退出后，以完整文件为准再执行一次增量核对。

### 14.3 本次恢复记录（2026-09-21）

本次使用的备份目录：

```text
C:\Users\weath\Documents\Codex\session-merge-backups\20260921-143406
```

已生成的可复核文件：

```text
dry-run-report-v2.json
apply-report.json
label-repair-report.json
```

恢复脚本位于项目目录：

```text
scripts/merge_codex_session_contexts.py
scripts/restore_codex_session_labels.py
```

脚本会：

- 按内容哈希复制另一端缺失的会话与附件；
- 合并附件清单，不以一端清单覆盖另一端；
- 使用原子替换写入统一的 `session_index.jsonl`；
- 遇到同路径但内容不同时报告冲突，不自动覆盖；
- 保留原有会话 ID 和 JSONL 正文。

本次发现两条客户端索引没有对应的会话 JSONL 文件。它们已在迁移报告中记录为“索引存在、正文缺失”，索引记录本身没有被删除，也没有伪造正文。后续若在旧备份中找到对应 JSONL，可按 ID 增量补回。

WSL 客户端如果左侧仍只显示原有会话，先检查 `state_5.sqlite` 的 `threads` 数量。新版 Codex 会把会话列表投影写入该表；仅合并 `session_index.jsonl` 不足以让已运行的 WSL 客户端显示导入会话。可使用以下脚本把客户端的已备份线程和历史事件事务性导入 WSL 投影：

```text
scripts/import_client_history_into_wsl_projection.py
```

该脚本会先创建 WSL SQLite 的一致性备份，再导入统一索引中的线程、事件和关联记录，并将已有会话的 `rollout_path` 改为 `/root/.codex/sessions/...`。导入结束后重载 WSL 的 VS Code 窗口或完全重启 Codex，令界面重新读取投影数据库。

最近会话菜单显示的是 `threads.name`，而不是只显示 `session_index.jsonl` 或 `threads.title`。因此完成导入后还要让 `threads.name` 同步为带来源前缀的显示标题：

```text
scripts/normalize_codex_display_names.py
```

顶部的 `Search recent chats` 弹出菜单本身只展示最近会话；要查看完整历史，应点击菜单底部的 `View all (...)` 或进入本地会话历史页。`Failed to load cloud chats` 只表示云端聊天搜索失败，不代表本地 JSONL 或 SQLite 历史丢失。

### 14.4 恢复后的验证清单

两端分别确认：

1. 索引中的会话 ID 集合相同；
2. `<客户端>` 与 `<wsl>` 前缀数量符合原始来源；
3. 一个旧客户端会话和一个旧 WSL 会话均可打开；
4. 包含代码块和附件的会话内容完整；
5. 历史 `speedy` 会话不会因缺少 provider 配置而无法打开；
6. 已结束会话的 JSONL 在两端哈希一致；
7. 当前仍在运行的会话结束后，再执行一次只读核对，确保没有剩余内容差异。
