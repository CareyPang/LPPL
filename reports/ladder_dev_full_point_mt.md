# 多重比较诊断（ladder_dev_full_point；开发段，不是样本外）

- 逐日损失矩阵：920 日 × 48 配置（来源 `data/oof/ladder_dev_full_point_losses.parquet`）
- PBO（CSCV，S=16）：**0.776**（样本内最优配置在样本外落到中位数以下的概率；> 0.5 说明选择基本是运气）
- SPA p 值（所有配置相对 R0，80 日块 bootstrap，B=2000）：**0.6595**；SPA 最优候选 R2_bsadf250_psy_z_C0.1
- n_combos: 12870.0000
- logit_mean: -0.9156
