# TraceCascade 项目企划与交付状态

## 定位

TraceCascade 是本地优先的“变更影响模拟器”：在修改合同、字段、指标、流程、代码模块或 API 前，推演下游影响，并让每一步结论都能追溯到原始证据和人工决策。

## 已完整交付的 v1

| 能力 | 交付状态 | 验收方式 |
|---|---|---|
| 严格图模型与影响传播 | 完成 | 循环可终止、最强路径确定、证据失败即拒绝运行 |
| Markdown/CSV/JSON 摄取 | 完成 | 多来源合并；冲突 ID、未知实体和伪造证据失败关闭 |
| 实体对齐与撤销 | 完成 | 显式规则、原始字节账本、精确恢复 |
| 图差异与报告比较 | 完成 | 增删改和影响变化均输出机器可读 JSON |
| 人工审核工作台 | 完成 | 仅监听回环地址、CSRF、输出转义、角色权限 |
| 可验证审计 | 完成 | SHA-256 链、可选强制 HMAC、并发写入锁、篡改检测 |
| 只读连接器 | 完成 | Python AST 扫描、有限 GET-only GitHub 快照 |
| ReproForge 导出 | 完成 | 所有受影响节点必须映射，输出任务依赖 DAG 并实际执行验收 |
| 加密恢复 | 完成 | scrypt + AES-256-GCM、路径/体积/符号链接防护、恢复测试 |
| 工程化发布 | 完成 | 打包安装、Windows/Linux CI、端到端示例、规模基准 |

## 架构

```text
Markdown / CSV / JSON / Python / GitHub snapshot
                         ↓
          strict evidence-backed graph
              ↓ align / diff / undo
                 what-if scenario
                         ↓
 deterministic cycle-safe impact propagation
                         ↓
       JSON + Markdown + local review UI
                         ↓
   signed audit decisions / reviewed graph
                         ↓
             ReproForge execution DAG
```

## 真实用途

- 数据字段或指标口径变化前，找到任务、报表和业务承诺的连锁影响。
- 删除 API 属性前，找到客户端、测试、文档与发布流程的依赖路径。
- 合同付款周期变化前，核对发票流程、现金流模型和提醒规则。
- Python 工程改模块前，从 import 关系生成可核验的局部依赖图。

## 安全与可信原则

1. 每条边必须有证据，推测不能冒充事实。
2. 所有破坏性变换都输出新文件；实体合并可精确撤销。
3. 远程连接器只读且有文件数/字节数上限。
4. 审核记录并发安全、可验证、可选密钥认证。
5. 备份在写盘前认证，恢复拒绝路径穿越和压缩炸弹式扩张。

## 边界与后续方向

v1 是完整的本地/小团队产品，不宣称是多租户 SaaS。它不自动证明因果、不代替法律或安全判断，也不安全执行不可信命令。未来可继续做组织级身份接入、托管服务、更多语言/schema 连接器和增量图存储；这些不属于当前已完成范围。
