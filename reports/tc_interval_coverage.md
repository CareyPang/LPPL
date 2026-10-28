# t_c 90% 区间覆盖率（阶段 3b）

名义水平 90%。profile = 剖面似然（未含 modified 校正）；bootstrap = 残差循环块 bootstrap（B=50，块长 10）。

| method    |   coverage |   med_width |
|:----------|-----------:|------------:|
| bootstrap |      0.875 |      34.707 |
| profile   |      0.764 |      32.5   |

## 分场景
|                                    |   coverage |   med_width |
|:-----------------------------------|-----------:|------------:|
| ('base', 'garch', 'bootstrap')     |      0.917 |      25.708 |
| ('base', 'garch', 'profile')       |      0.667 |      25     |
| ('base', 'iid', 'bootstrap')       |      0.833 |      26.838 |
| ('base', 'iid', 'profile')         |      0.667 |      26     |
| ('short', 'garch', 'bootstrap')    |      0.833 |      18.983 |
| ('short', 'garch', 'profile')      |      0.917 |      32.5   |
| ('short', 'iid', 'bootstrap')      |      0.833 |      23.727 |
| ('short', 'iid', 'profile')        |      0.833 |      29.5   |
| ('weak_osc', 'garch', 'bootstrap') |      0.917 |      61.579 |
| ('weak_osc', 'garch', 'profile')   |      0.75  |      69.5   |
| ('weak_osc', 'iid', 'bootstrap')   |      0.917 |      59.056 |
| ('weak_osc', 'iid', 'profile')     |      0.75  |      51.5   |
