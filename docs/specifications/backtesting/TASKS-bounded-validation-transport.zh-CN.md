# 有界校验传输任务

[英文规范版](TASKS-bounded-validation-transport.md)。[规格](SPEC-bounded-validation-transport.zh-CN.md)。

- [x] BVT-T01：冻结双语协议、预算、所有权及固定测量顺序，保留已有改动。
- [x] BVT-T02：针对未改动的纯校验，证明无损编码、帧及完整流校验。
- [x] BVT-T03：验证总额准入、重叠、超大输入回退及同时刻内存观测。
- [x] BVT-T04：验证观察者取消、物理排空、子进程故障及清理屏障。
- [x] BVT-T05：执行固定对比、相关回归/变异，记录全部失败并决定 P1。
- [x] BVT-T06：发布双语证据及结论；仅全部前置条件通过后推进生产集成。

P0 已完成。P1 暂缓：并发 SQL 批次的计费范围超过不变预算。见[验证报告](../../verification/bounded-validation-transport-2026-10-22.zh-CN.md)。
