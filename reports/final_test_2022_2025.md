# 最终测试段 2022-01–2025-08（只跑一次） 报告（只报告，不选择；冻结见 docs/dev_freeze.md）

开发段 2000–2018 一次拟合 → 最终测试段 2022-01–2025-08（只跑一次）前推。基线 R0 = 开发段基率。ΔBrier 为负=优于基率；90% 区间为 80 日块 bootstrap。
判据（用户 2026-10-26 接受）：(i) ΔBrier 区间上界<0；(ii) ≥4/6 指数 A1 循环平移 p≤0.05 且 A2≥0.5（H=120）；(iii) 留出任一指数/年份不翻转。

## 1. 样本
- 顶部（稀疏 as-of 网格，R2 特征）：最终测试段 2022-01–2025-08（只跑一次） n=1239，正标签 62，指数 7（含科创50 自 2020）。
- 底部（逐日，指数+个股）：最终测试段 2022-01–2025-08（只跑一次） n=190210，正标签 11610。

## 2. 判据 (i)：概率模块
### 2.1 顶部 p20 = R2（GSADF bsadf500_psy）
```
level      features   brier  log_loss     ece     bss  pr_auc  dbrier_vs_R0  ci_lo_R0  ci_hi_R0 pass_i_vs_R0  n_events  hit_rate  false_alarm_rate
   R0 dev base rate 0.04966   0.21321 0.04609 0.00000 0.34873           NaN       NaN       NaN          NaN       NaN       NaN               NaN
   R2  bsadf500_psy 0.04808   0.19964 0.02630 0.03175 0.08795      -0.00158  -0.00231  -0.00003         True      15.0   0.26667           0.04758
```

**结论：判据 (i) 通过**（点估计 -0.00158，上界 -0.00003）；判据 (iii) **不满足**：留出表中 4 个留出子集的区间上界回到 0 以上。
Platt（套用校准段固定 (a,b)，不重拟合）：
```
 level        a        b  brier_raw  brier_platt  ece_raw  ece_platt    n  pos
top_R2 -0.86604 -4.98305    0.04808      0.04855   0.0263    0.03757 1239   62
```

校准段固定的 a<0（方向反转）套到测试段使 Brier 变差（brier_platt > brier_raw）：校准段学到的反向关系不可迁移。

留出（LOCO / 留出年）：
```
    holdout level  dbrier_vs_R0    ci_lo    ci_hi  pass_i    n
ex_sh000001    R2      -0.00141 -0.00209  0.00004   False 1062
ex_sh000016    R2      -0.00179 -0.00246 -0.00039    True 1062
ex_sh000300    R2      -0.00161 -0.00232 -0.00013    True 1062
ex_sh000688    R2      -0.00171 -0.00247 -0.00037    True 1062
ex_sh000905    R2      -0.00172 -0.00269  0.00012   False 1062
ex_sz399001    R2      -0.00153 -0.00231  0.00010   False 1062
ex_sz399006    R2      -0.00126 -0.00222  0.00043   False 1062
    ex_2022    R2      -0.00259 -0.00331 -0.00140    True  903
    ex_2023    R2      -0.00070 -0.00141 -0.00027    True  896
    ex_2024    R2      -0.00130 -0.00131 -0.00129    True  903
    ex_2025    R2      -0.00170 -0.00221 -0.00129    True 1015
```

标签变体（§3 步骤 5；冻结标签为 main，变体只报告不替换）：

### 2.2 底部链 R0 → B1 → B2 → B3
```
level  dbrier_vs_R0  ci_lo_R0  ci_hi_R0 pass_i_vs_R0   dbrier    ci_lo   ci_hi   brier     ece  pr_auc
   R0           NaN       NaN       NaN          NaN      NaN      NaN     NaN 0.05736 0.00679 0.05047
   B1       0.00349   0.00060   0.00708        False  0.00349  0.00060 0.00708 0.06085 0.04020 0.06188
   B2       0.00468   0.00123   0.00938        False  0.00119  0.00030 0.00243 0.06204 0.04315 0.05829
   B3       0.00461   0.00142   0.00888        False -0.00007 -0.00052 0.00036 0.06197 0.04363 0.06116
```

**结论：判据 (i) B1 未通过、B2 未通过、B3 未通过**。
仅指数子样本：
```
level  dbrier_vs_R0   ci_lo   ci_hi  pass_i    n
   B1       0.01363 0.00181 0.02928   False 5038
   B2       0.01991 0.00349 0.04606   False 5038
   B3       0.02026 0.00412 0.04537   False 5038
```

Platt（仅记录）：
```
    level       a        b  brier_raw  brier_platt  ece_raw  ece_platt      n   pos
bottom_B2 0.30202 -1.47955    0.06204      0.05852  0.04315    0.02985 190210 11610
bottom_B3 0.28433 -1.52447    0.06197      0.05840  0.04363    0.02867 190210 11610
```

留出：
```
    holdout level  dbrier_vs_R0    ci_lo   ci_hi  pass_i      n
ex_sh000001    B1       0.00345  0.00060 0.00699   False 189489
ex_sh000001    B2       0.00461  0.00123 0.00924   False 189489
ex_sh000001    B3       0.00454  0.00140 0.00869   False 189489
ex_sh000016    B1       0.00346  0.00060 0.00702   False 189463
ex_sh000016    B2       0.00465  0.00122 0.00932   False 189463
ex_sh000016    B3       0.00460  0.00141 0.00884   False 189463
ex_sh000300    B1       0.00346  0.00060 0.00702   False 189483
ex_sh000300    B2       0.00465  0.00122 0.00931   False 189483
ex_sh000300    B3       0.00458  0.00141 0.00881   False 189483
ex_sh000688    B1       0.00343  0.00060 0.00692   False 189524
ex_sh000688    B2       0.00461  0.00121 0.00917   False 189524
ex_sh000688    B3       0.00453  0.00140 0.00870   False 189524
ex_sh000905    B1       0.00345  0.00060 0.00701   False 189467
ex_sh000905    B2       0.00462  0.00122 0.00924   False 189467
ex_sh000905    B3       0.00454  0.00140 0.00873   False 189467
ex_sz399001    B1       0.00344  0.00059 0.00700   False 189483
ex_sz399001    B2       0.00459  0.00122 0.00920   False 189483
ex_sz399001    B3       0.00452  0.00139 0.00868   False 189483
ex_sz399006    B1       0.00345  0.00060 0.00700   False 189523
ex_sz399006    B2       0.00462  0.00123 0.00926   False 189523
ex_sz399006    B3       0.00456  0.00141 0.00875   False 189523
    ex_2022    B1       0.00426  0.00031 0.00920   False 142260
    ex_2022    B2       0.00588  0.00125 0.01210   False 142260
    ex_2022    B3       0.00579  0.00153 0.01133   False 142260
    ex_2023    B1       0.00484  0.00112 0.00935   False 139645
    ex_2023    B2       0.00625  0.00176 0.01239   False 139645
    ex_2023    B3       0.00608  0.00201 0.01162   False 139645
    ex_2024    B1       0.00060 -0.00031 0.00146   False 137950
    ex_2024    B2       0.00124  0.00020 0.00215   False 137950
    ex_2024    B3       0.00155  0.00032 0.00270   False 137950
    ex_2025    B1       0.00416  0.00052 0.00864   False 150775
    ex_2025    B2       0.00523  0.00084 0.01125   False 150775
    ex_2025    B3       0.00494  0.00089 0.01042   False 150775
```


## 3. 判据 (ii)：LPPLS 置信度报警（产品尺度 6–12 月 / 12–24 月，q=0.05）
按指标 × H 汇总（n_pass = A1 p≤0.05 且 A2≥0.5 的指数数；pass_ii = n_pass≥4；loco_min = 留出任一指数后的最小 n_pass，pass_iii_loco = 留出后仍 ≥4）：
```
             indicator   H  n_symbols  n_pass  pass_ii  loco_min  pass_iii_loco  A1_med  A1_null_med  A2_med  n_alarm_total
           box__12-24m  60          7       1    False         0          False     0.0      0.12277     0.0             91
           box__12-24m 120          7       1    False         0          False     0.0      0.16356     0.0             91
            box__6-12m  60          7       1    False         0          False     0.0      0.09350     0.0             74
            box__6-12m 120          7       1    False         0          False     0.0      0.14050     0.0             74
     g_fco_end__12-24m  60          7       0    False         0          False     NaN          NaN     NaN              0
     g_fco_end__12-24m 120          7       0    False         0          False     NaN          NaN     NaN              0
      g_fco_end__6-12m  60          7       0    False         0          False     NaN          NaN     NaN              0
      g_fco_end__6-12m 120          7       0    False         0          False     NaN          NaN     NaN              0
g_fco_standard__12-24m  60          7       0    False         0          False     0.0      0.00000     0.0              7
g_fco_standard__12-24m 120          7       0    False         0          False     0.0      0.00000     0.0              7
 g_fco_standard__6-12m  60          7       0    False         0          False     0.0      0.01044     0.0             24
 g_fco_standard__6-12m 120          7       0    False         0          False     0.0      0.01131     0.0             24
```

**判据 (ii)：无组合通过。**
Holm 修正后 A1 显著指数数（补充，不改变判据口径）：
```
             indicator   H  n_pass_raw  n_pass_holm
           box__12-24m  60           1            1
           box__12-24m 120           1            1
            box__6-12m  60           1            1
            box__6-12m 120           1            1
     g_fco_end__12-24m  60           0            0
     g_fco_end__12-24m 120           0            0
      g_fco_end__6-12m  60           0            0
      g_fco_end__6-12m 120           0            0
g_fco_standard__12-24m  60           0            0
g_fco_standard__12-24m 120           0            0
 g_fco_standard__6-12m  60           0            0
 g_fco_standard__6-12m 120           0            0
```

逐指数明细（H=120）：
```
  symbol              indicator  n_alarm  n_tops    A1  A1_null  A1_p  A2  A2_null  A2_p
sh000001             box__6-12m       25       1 0.200    0.003 0.000 1.0    0.073 0.073
sh000001            box__12-24m        5       1 0.000    0.000 1.000 0.0    0.000 1.000
sh000001  g_fco_standard__6-12m        0       1   NaN      NaN   NaN NaN      NaN   NaN
sh000001 g_fco_standard__12-24m        0       1   NaN      NaN   NaN NaN      NaN   NaN
sh000001       g_fco_end__6-12m        0       1   NaN      NaN   NaN NaN      NaN   NaN
sh000001      g_fco_end__12-24m        0       1   NaN      NaN   NaN NaN      NaN   NaN
sh000016             box__6-12m       17       3 0.000    0.059 1.000 0.0    0.237 1.000
sh000016            box__12-24m       25       3 0.000    0.164 1.000 0.0    0.296 1.000
sh000016  g_fco_standard__6-12m        0       3   NaN      NaN   NaN NaN      NaN   NaN
sh000016 g_fco_standard__12-24m        0       3   NaN      NaN   NaN NaN      NaN   NaN
sh000016       g_fco_end__6-12m        0       3   NaN      NaN   NaN NaN      NaN   NaN
sh000016      g_fco_end__12-24m        0       3   NaN      NaN   NaN NaN      NaN   NaN
sh000300             box__6-12m        2       1 0.000      NaN   NaN 0.0      NaN   NaN
sh000300            box__12-24m       11       1 0.000    0.072 1.000 0.0    0.127 1.000
sh000300  g_fco_standard__6-12m        3       1 0.000    0.000 1.000 0.0    0.000 1.000
sh000300 g_fco_standard__12-24m        1       1 0.000      NaN   NaN 0.0      NaN   NaN
sh000300       g_fco_end__6-12m        0       1   NaN      NaN   NaN NaN      NaN   NaN
sh000300      g_fco_end__12-24m        0       1   NaN      NaN   NaN NaN      NaN   NaN
sh000688             box__6-12m        4       2 0.000    0.053 1.000 0.0    0.072 1.000
sh000688            box__12-24m        7       2 0.714    0.000 0.000 1.0    0.000 0.000
sh000688  g_fco_standard__6-12m       16       2 0.000    0.011 1.000 0.0    0.028 1.000
sh000688 g_fco_standard__12-24m        6       2 0.000    0.000 1.000 0.0    0.000 1.000
sh000688       g_fco_end__6-12m        0       2   NaN      NaN   NaN NaN      NaN   NaN
sh000688      g_fco_end__12-24m        0       2   NaN      NaN   NaN NaN      NaN   NaN
sh000905             box__6-12m       20       3 0.000    0.222 1.000 0.0    0.431 1.000
sh000905            box__12-24m       18       3 0.000    0.341 1.000 0.0    0.349 1.000
sh000905  g_fco_standard__6-12m        4       3 0.000    0.360 1.000 0.0    0.383 1.000
sh000905 g_fco_standard__12-24m        0       3   NaN      NaN   NaN NaN      NaN   NaN
sh000905       g_fco_end__6-12m        0       3   NaN      NaN   NaN NaN      NaN   NaN
sh000905      g_fco_end__12-24m        0       3   NaN      NaN   NaN NaN      NaN   NaN
sz399001             box__6-12m        3       2 0.333    0.271 0.557 0.5    0.278 0.557
sz399001            box__12-24m       12       2 0.000    0.269 1.000 0.0    0.268 1.000
sz399001  g_fco_standard__6-12m        0       2   NaN      NaN   NaN NaN      NaN   NaN
sz399001 g_fco_standard__12-24m        0       2   NaN      NaN   NaN NaN      NaN   NaN
sz399001       g_fco_end__6-12m        0       2   NaN      NaN   NaN NaN      NaN   NaN
sz399001      g_fco_end__12-24m        0       2   NaN      NaN   NaN NaN      NaN   NaN
sz399006             box__6-12m        3       3 0.000    0.267 1.000 0.0    0.095 1.000
sz399006            box__12-24m       13       3 0.000    0.272 1.000 0.0    0.173 1.000
sz399006  g_fco_standard__6-12m        1       3 0.000      NaN   NaN 0.0      NaN   NaN
sz399006 g_fco_standard__12-24m        0       3   NaN      NaN   NaN NaN      NaN   NaN
sz399006       g_fco_end__6-12m        0       3   NaN      NaN   NaN NaN      NaN   NaN
sz399006      g_fco_end__12-24m        0       3   NaN      NaN   NaN NaN      NaN   NaN
```

按年（报警日合计与 A1 中位数）：
```
             indicator  year  A1_H120  n_alarm
           box__12-24m  2022      1.0        5
           box__12-24m  2023      NaN        0
           box__12-24m  2024      0.0        3
           box__12-24m  2025      0.0       83
            box__6-12m  2022      1.0        6
            box__6-12m  2023      0.0       15
            box__6-12m  2024      0.0        3
            box__6-12m  2025      0.0       50
     g_fco_end__12-24m  2022      NaN        0
     g_fco_end__12-24m  2023      NaN        0
     g_fco_end__12-24m  2024      NaN        0
     g_fco_end__12-24m  2025      NaN        0
      g_fco_end__6-12m  2022      NaN        0
      g_fco_end__6-12m  2023      NaN        0
      g_fco_end__6-12m  2024      NaN        0
      g_fco_end__6-12m  2025      NaN        0
g_fco_standard__12-24m  2022      NaN        0
g_fco_standard__12-24m  2023      NaN        0
g_fco_standard__12-24m  2024      NaN        0
g_fco_standard__12-24m  2025      0.0        7
 g_fco_standard__6-12m  2022      NaN        0
 g_fco_standard__6-12m  2023      NaN        0
 g_fco_standard__6-12m  2024      0.0       10
 g_fco_standard__6-12m  2025      0.0       14
```


## 4. 多重比较（§3 步骤 4）
- 开发段阶梯 70 配置：CSCV-PBO 0.503、SPA p 0.1615（`reports/ladder_dev_full_v2_mt.md`）——开发段的配置选择本身接近运气水平，与校准段 R2 未通过一致。
- 开发段候选总数：阶梯 70 + 原版标准网格 108 + 尺度敏感性 162 = 340；原版标准/尺度敏感性的 A1 p 值在开发段未做多重比较修正，报告中已声明为开发段描述。
- 最终测试段 2022-01–2025-08（只跑一次）只评价冻结配置（R2 一个；LPPLS 2 尺度 × 3 规则 × 2 H），不再选择；§3 给出 Holm 修正作为补充。

## 5. 对抗性检查（§3 步骤 5）
- 标签扰动：见 §2.1 标签变体——share30/share70 与主标签同向（未通过），fixed15/sigma1.5 为负；结论依赖标签定义，按冻结以 main 为准。
- 安慰剂：LPPLS A1/A2 的零分布即报警序列循环平移（§3）；R2 概率模块的对照为开发段基率 R0。
- 留出指数 / 留出年：§2.1 顶部 R2 留出后 4 个子集上界转正（判据 iii 不满足）；§2.2 底部全部未通过且不翻转。

## 6. 结论与产品处置
- 顶部 p20（R2）：判据 (i) 通过、判据 (iii) 不满足 → 契约 `top.p20` 证据等级 `fail_i_iii`，不显示概率。
- 底部概率链 B1/B2/B3：判据 (i) **全部未通过** → `bottom.state_p/thrust_p` 不显示概率。
- LPPLS 置信度（泡沫状态）：判据 (ii) **无组合通过**（box 6–12 月 1/7，A1 中位 0 vs 随机 0.14；STANDARD 24 个报警日 A1=0；END 0 个报警日）。测试段每指数仅 1–3 个合格顶，2025 年报警（箱体后 2025-09 起的上涨）在 H=120 内未出现标签顶；三段合并：开发段有信号、校准段脆弱、测试段未通过 → 证据等级 `dev_only`，只作泡沫状态描述性分级显示，不作预测证据。
- 产品层按用户裁决改为原版输出形式：DS 置信度 / t_c 情景 / 泡沫大小与持续时间（`docs/dev_freeze.md` §6）。
- 本报告为最终测试段唯一一次运行的结果；不据此重选模型、标签或阈值。后续证据只来自 2026 起的前瞻日志（`forward_log/`）。