# Happier 复用清单

上游：happier-dev/happier，提交 `47de280241d02d8b338b4e62f39983679716b044`。
MIT 许可证原文位于 `src/upstream/LICENCE`；原始文件与 SHA-256 位于 `manifest.json`。

- `PushableAsyncIterable.ts`：原样复用，与冻结参考逐字相同。
- `backend.ts`：由上游 `ClaudeSdkAgentBackend.ts` 适配。保留可推送输入、会话 init 标识、工具调用 ID 校验、权限回调、显式 result 收尾与 abort 生命周期。删除语音、relay、后台子任务及上游内部依赖；query 改用固定的官方 Claude Agent SDK 0.2.123。
- 上游 `claudeExplicitRunnerStop.ts` 保留参考：停止必须等待真实受管进程退出；Python supervisor 负责进程组终止和回执。
- 原始 `.reference` 文件仅作审计，不参与编译，不宣称完整原版 Happier CLI 已被迁入。

本版 `policy.ts`、JSONL 控制面、Python 设备桥和业务审批是本项目新增实现。没有复制 Happier 账号、加密、云同步、移动端、终端 UI、模型凭据或任意协议兼容服务。

升级：手动选择提交 → 核对许可证与哈希 → 对比三份参考 → 更新适配和 SDK 锁 → Node 协议及 PostgreSQL/本机端到端回归 → 单独记录真实 Claude 验收。禁止跟随 dev 自动升级。
