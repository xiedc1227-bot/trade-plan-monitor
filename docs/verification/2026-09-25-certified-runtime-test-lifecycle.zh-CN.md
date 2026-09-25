# 已认证运行时生命周期测试修复（离线）

## RED 与原因

`test_certified_pipeline_recovers_evaluates_once_and_restarts` 在首次 `trade_cal` 请求处因 `RequestControlErrorCode.ERROR` 失败。临时内存追踪显示受保护客户端抛出 `RuntimeError("provider certification is not current")`。旧测试直接构造 `_ProductionRuntimeState`，只调用 `probe_capabilities`，跳过数据库打开与存活准入，并将每次调用都会变化的 `uuid4` 作为运行代次回调。其测试搭建已不满足生产准入要求。

## 修复与验证

测试现创建已安装的 `create_monitor_composition`，启动并停止第一代受控运行时，再在同一临时 SQLite 数据库上启动第二个组合。执行精确分钟截止点前，断言数据库就绪、存活所有权、已绑定的行情恢复状态和当前运行代次。假 SDK 的“没有被占用的数据库连接”断言现指向每代组合的实际 engine。首次截止点提交一条评估；第一代重复执行以及重启后执行同一截止点，均不增加评估或 `rt_min` 请求。重启后的持久决策头保持不变。

专项测试通过。`test_certified_production_runtime.py`、`test_production_certification_gate.py` 与 `test_live_pipeline_acceptance.py` 整组回归 **72 项通过**。未修改生产安全门禁。本次仅修复测试夹具，不代表 C1 关闭或真实行情源/权限声明。未请求真实 Tushare、发送外部通知、迁移用户数据库、推送或部署。
