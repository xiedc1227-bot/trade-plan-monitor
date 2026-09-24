# 规格：provider-contract

> 本实现契约来自已批准提案 runtime-recovery 的 D1/D6；用户于 2026-09-21 授权实现。英文为规范输入，本文件为中文副本。
## 目标

将数据解释规则的持久证据，与当前凭证、权限和可用性分离。实现 A01–A02，不把过期的运行观测当作当前健康状态。
## 契约

- 历史读取保留结构、大小、规范哈希、归一化端点、非未来时间和范围校验；仅忽略七天年龄限制。原有时效读取保持原契约。
- 语义旁文件包含版本、surface、endpoint、profile、interval/endpoints、已验证时间标签、明确适配器兼容关系、来源及 semantic revision。不含凭证或当前 READY 状态。
- 兼容校验检查实际安装 SDK 与应用适配器映射。版本 1 仅支持已评审的 Tushare 1.4.29 适配器。未知兼容关系关闭相关能力。
- 股票与指数记录独立。仅导入已验证范围；不得提升未验证标签、缺失的 399107.SZ 证据或延期支持的 BSE。
- Semantic revision 包含解释字段，排除 verifiedAt/来源时间戳。仅元数据变化的再次导入无害。写入原子、幂等，原始证据不变。哈希用于完整性，不是身份认证。
- 生产请求在获取数据前检查已安装解释身份。相关配置或不兼容语义发生漂移时，阻断旧数据源，并要求安全停止、人工修正后启动新进程。停止须在释放存储前排空旧工作线程及其持久结果；旧 generation 不得提交。仅语义元数据刷新不要求重启。
## 结构与风格

负责 runtime/provider_contract.py 和 live_profiles.py。冻结类型记录、窄边界校验函数；导入过程不得请求行情源。
## 命令与测试

`.\.venv\Scripts\python.exe -m pytest tests/unit/test_provider_contract.py tests/unit/test_live_certification_profiles.py -q`
使用临时证据文件；测试过龄、损坏、未来、不兼容及部分范围。保留现有认证测试。
## 边界

始终保留原始证据和严格校验。新增 SDK 支持或真实认证前询问。禁止复制旧健康状态为当前健康状态，禁止修改凭证。
