# P-LNN来源核验与84案例执行条件

核验日期：2026-11-16。交接对象：Devin。只读核验，没有安装神经网络依赖、加载模型、训练、推理或拟合。此文补充既有三臂任务，不改变完整周期1.5、未来域、评分和旧结果。

## 本轮结论

**代码存在已核验；可直接使用的作者P-LNN代码/权重来源链尚未建立。** 查到两份第三方实现，都没有在所查完整tree或release发布checkpoint。README中的加载示例不是实际权重资产。当前P臂为 `NOT_RUN_MODEL_UNAVAILABLE`，三臂A为 `BLOCKED_CHECKPOINT_PROVENANCE`，B保持禁用。

这是一轮有边界检索，不能据此断言作者从未发布、私人工作区不存在权重。公开检索包含论文v1、作者关联传统库、作者研究页、两份第三方仓库的固定提交/tree/releases，以及P-LNN/Poly-LPPLS/Deep LPPLS weights、checkpoint、download、HuggingFace关键词。OpenReview论坛遇浏览器验证，标 `NOT_INSPECTED`。本地仅检查既有LPPL开发目录与torch/HuggingFace缓存中名称匹配的模型文件，没有找到；未扫描全部磁盘。

## 逐源核验

| 来源 | 固定版本与证据 | 结论 |
|---|---|---|
| [Deep LPPLS论文v1](https://arxiv.org/html/2405.12803v1) | 正文无作者代码/权重下载链接；论文页面标CC BY-NC-SA 4.0 | VERIFIED：文稿许可；软件/权重许可不能由此推定 |
| [Boulder-Investment-Technologies/lppls](https://github.com/Boulder-Investment-Technologies/lppls/tree/eaa0da95b76b63f2b90df7b839d62150494a464b) | 作者关联的传统库；MIT；44项完整tree未见M/P-LNN或checkpoint；2个release无附加资产 | VERIFIED：传统库；不能当Deep LPPLS发布包 |
| [mvs-86/lppls_py](https://github.com/mvs-86/lppls_py/tree/a81f4f685e1874810f912246f439f644845cf394) | 19个文件，有Keras P-LNN与训练代码；无checkpoint；releases=[]；`.gitignore`排除models/、keras/h5/ckpt | VERIFIED：第三方代码。README作者声明MIT，但无独立LICENSE，权重授权未建立 |
| [unbalancedparentheses/fatcrash](https://github.com/unbalancedparentheses/fatcrash/tree/dba203828e35b97342f87d514003c7ae6c75e576) | 226项完整tree，有PyTorch P-LNN；无checkpoint；releases=[]；API license=null且未见许可证文件 | VERIFIED：第三方实现。可复用许可与权重来源NOT_ESTABLISHED |
| [Raissi研究页](https://maziarraissi.github.io/research/) | 本次页面检查未找到该项目资源入口 | 有界检查；不证明其他位置不存在 |

机器记录见 [source-verification.json](source-verification.json)。DS-LPPLS是另一个项目，不能用其名称、Confidence或结果表代替Deep LPPLS P-LNN权重核验。FCO商业页面的Deep LPPLS介绍也不构成开源checkpoint发布。

## 不能直接复用第三方整条推理流程

### Keras实现：mvs-86

- [`lppls/plnn.py`](https://github.com/mvs-86/lppls_py/blob/a81f4f685e1874810f912246f439f644845cf394/lppls/plnn.py)：252输入、四个252宽ReLU隐藏层、线性3输出，顺序 `[tc_norm,m,omega]`。这是该代码的架构，不是已验证作者checkpoint的shape。
- [`dataset.py`](https://github.com/mvs-86/lppls_py/blob/a81f4f685e1874810f912246f439f644845cf394/lppls/dataset.py#L44)：训练坐标linspace(0,1,252)，tc=[1,1+50/252]、m=[.1,.9]、omega=[6,13]。L113–135先把干净曲线min-max，再加噪声，最终没有再min-max；与推理对带噪实测窗口重新min-max存在分布差异，不能当作完全一致预处理。
- [`inference.py`](https://github.com/mvs-86/lppls_py/blob/a81f4f685e1874810f912246f439f644845cf394/lppls/inference.py#L93)：按首尾日历跨度外推tc、使用训练域的窄过滤，并静默丢弃失败窗口。不能接用此包装器；独立适配器必须保留计划窗口和失败原因，使用项目交易时钟、共同搜索域和资格。
- `requirements.txt`是宽松最低版本，不是可重复依赖锁；运行时必须冻结Python/NumPy/SciPy/Keras/TensorFlow及设备。原型不要求PyTorch；不得仅凭模型名选加载框架。

### PyTorch实现：fatcrash

- [`python/fatcrash/nn/plnn.py`](https://github.com/unbalancedparentheses/fatcrash/blob/dba203828e35b97342f87d514003c7ae6c75e576/python/fatcrash/nn/plnn.py#L37)：252→512→256→128→64→3；与上述Keras架构不同，不可交换权重。
- L179–195截末252、短输入左补0；L205用当前n_obs+50解码，L213–214裁剪m/omega；L235以 `1/(1+rss*100)`构造confidence。以上不能带入本pilot：整窗口不得被替换、不得暗裁域外初值、该confidence不作为结构比例或顶部概率。
- [`synthetic.py`](https://github.com/unbalancedparentheses/fatcrash/blob/dba203828e35b97342f87d514003c7ae6c75e576/python/fatcrash/nn/synthetic.py#L188)训练标签tc/(n_obs+50)。假设以后取得此252输入实现的权重，令原始输出q，则训练时钟0..251、分母302，映射为 `tc_original=t1+(302*q/251)*(t2-t1)`。这是特定实现的代数推导，不是通用P-LNN映射，更不是本轮已验证模型。
- 原加载器L85用 `torch.load(weights_only=False)`；不得直接执行未核来源的pickle或第三方整包初始化。取得可信资产后用对应框架的受限加载方式，显式CPU、shape/dtype/有限值校验并记录版本；不为了加载而降级安全选项。若必须依赖任意自定义对象，预检失败并列明原因。

对Keras的归一化时间模型，若checkpoint确实使用0..1坐标，映射是 `tc_original=t1+tc_norm*(t2-t1)`。**先确定checkpoint的时钟/标签定义，再选择映射，绝不按本轮窗口长度猜测。** 输入只用当前asof内完整窗口，按冻结交易时钟重采样为252点；60/180/360等原始点数不等于网络时钟。停牌/缺失按项目冻结规则处理，不用平均日历间距替代交易序号。所有精修/SSE/结构过滤回到原始窗口。

## 交给Devin的顺序与硬门

1. **D00：先交预检记录。** 检查Devin工作区已有资产；若存在权重，不能只填路径，须填原始URL/作者或第三方身份、代码commit、实际bytes/SHA-256、适用许可、网络架构、输入输出、scaler/时钟、训练分布/选择依据。找不到就如实保留null和阻断码，不下载来源不明权重、不自动开训。
2. **D01：冻结84例和工程fixture。** 按W04生成样本身份/参数/seed/hash；真实仅已消费开发段。完成下表，不启动B。可先准备数据和D/G基线；若在A预算内运行D/G的84例，报告 `A_PARTIAL_DG_ONLY`，P的84个槽位标NOT_RUN，不能叫三臂完整对照。没有checkpoint时不执行P归因诊断/推理计时，也不耗算力重复搜索。
3. **D02：权重门通过才执行P。** 每例只生成一个网络初值，再独立TRF；不隐藏回退、投影或候选集成。沿用相同84例和原预算；D/G效果缓存只有身份完全一致才可复用。新增P的速度比较要在同设备/线程配置下完成预登记计时案例，不能把D/G缓存读取与P新推理相比。
4. **D03：先交A报告。** 报告表包括总耗时p50/p95、首次导入/加载、精修占比、总CPU、原序列SSE、合成参数误差、域外/边界/失败、负例错误结构率。逐例配对，噪声压力组分开；真实顶部日不当潜在tc参数真值。比较完整流水线，也保留12例统一TRF归因诊断。训练未知成本不填0。
5. **D04：本次交接执行终点是A报告。** B文件保留但 `enabled=false`。只有完整三臂A通过工程门并完成耗时/质量审查后，才另提交 `A_DECISION.json` 和B启用变更；不能仅因SSE下降就自动开始阶段顶重放。若P不可用，结论是证据不完整，不能把D/G胜出写成P劣于。GRU/LSTM保持下一候选；G-LPPLS、神经后验、自对弈/RL均不混入。

本轮不另造“提高准确率X%”或任意通用胜出门。A报告须给出值得继续的代价与拟合质量依据、失败容忍建议；这些若要成为后续固定门，必须在读取B效果之前封存。现阶段只可宣布工程完成、部分完成、回归或证据不足，不能宣布市场预测优越性。

## 必须先通过的fixture

| 检查 | 通过条件 |
|---|---|
| 身份/框架 | 实际资产hash、格式、层键/shape匹配固定架构；不是随机初始化或未训练demo |
| 输出顺序与标度 | 固定3个手算theta往返还原，t1非零也成立；错误顺序/未知scaler必须拒绝 |
| 整窗口输入 | 60/180/360点都保留完整区间，不补0、不截末252；网络重采样与原始精修数据分开hash |
| 时间映射 | 覆盖60/252/756、非零原点、周末/节假日/停牌规则；不把重采样点直接当交易日 |
| 非法输入输出 | 常数、NaN/Inf、非正价格、域外theta、tc<=t2都保留明确状态，不静默删窗或clip |
| 独立精修 | 同一原序列/搜索界/四线性消元；保留初值、精修值、各阶段SSE和终止原因 |
| 因果与成本 | 修改asof之后数据不改当前输出；冷/热计时分开，nfev/线性求解数和预算跨续跑累计 |
| 结果不覆盖 | 新run_id、旧hash清单、expected/completed/failed/pending可加总；P未跑的槽位明确保留 |

本次固定门：A仍最多324任务单元，墙钟20分钟/累计CPU80分钟，最多4工作进程、每进程BLAS1、内存8GiB；任一限额先到则保存pending，不重启绕限。模型训练、购置资源、全量重跑、B自动执行、合并、部署、发布均关闭。

## 必交文件

除原W08外，补 `source_preflight.json`、`checkpoint_provenance.json`、`adapter_contract.json`、`fixture_results.json`、`sample_selection.json`、`A_REPORT.md`、`A_DECISION.json`。没有权重时也交这些文件的实际状态，`checkpoint_sha256=null`、`weight_license=null`、`inference_verified=false`，不得把TODO填成VERIFIED。

当前交付状态：代码/公开资产核验 **VERIFIED**；作者checkpoint可用性/授权 **NOT_ESTABLISHED**；P模型运行 **NOT_RUN_MODEL_UNAVAILABLE**；84例实际执行 **NOT_RUN**；B **HOLD_PENDING_PHASE_A_REVIEW**。PR任务已交接不等于外部Devin会话已启动，启动与执行完成需由会话ID/日志证明。
