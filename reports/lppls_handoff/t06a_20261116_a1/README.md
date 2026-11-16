# T06a 预注册冻结

`preregistration.json` 在 T03 运行前冻结，定义 B0/W1/C1 的资产、计划窗口、过滤、主指标 S10、统计方法、负担容忍度及结果判定；文件 SHA-256 为 `3e8651b1ccaf2bc7dc944af746b03917f6291ad537b979b0612556278b2daaab`。

本轮只使用已经消费过的开发样本，结果属于 `development_diagnostic`，不是新的留出集或独立确认。T03 pilot 仅用于工程与耗时检查，不用于效果比较。G1 明确为 `DEFERRED_NOT_PREREGISTERED`，不得根据本轮结果补登记或调阈值。

T03 各臂均使用 T01 `future_fullcycles_1p5_v1` 的资格筛选。PR #50 的旧资格框（m∈[0.1,0.9]、ω∈[6,13]、ahead≤90）不适用：B0 遵守预注册的 T01 合同；仅复用 PR #50 的尺度/聚类聚合几何，不引入额外 90-session 截断。
