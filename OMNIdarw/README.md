# OMNI 参数时间序列绘图模块

目录名 `OMNIdarw` 沿用仓库原始拼写。本模块的目标很明确：从 NASA CDAWeb HAPI 接口抓取指定事件窗口内的 OMNI 数据，并生成可直接用于论文的时间序列图。

当前脚本只有一个：

- [scripts/plot_omni_timeseries.py](scripts/plot_omni_timeseries.py)

## 获取的数据

脚本固定访问以下数据集：

| 数据集 | 参数 | 用途 |
| --- | --- | --- |
| `OMNI_HRO2_1MIN` | `BZ_GSM` | IMF Bz 1 分钟分辨率 |
| `OMNI2_H0_MRG1HR` | `DST1800`, `KP1800` | Dst 与 Kp 指数 |

## 当前事件窗口

事件窗口在脚本常量 `EVENT_WINDOWS` 中定义，目前包括：

- `20240510_20240513`
- `20241010_20241013`
- `20241231_20250103`

如果需要新增事件，只需在 `EVENT_WINDOWS` 中补充新的 `EventWindow`。

## 输出内容

脚本会同时输出数据文件和图像文件。

### CSV

保存在：

```text
OMNIdarw/outputs/data/
```

生成文件包括：

- `omni_bz_1min_<slug>.csv`
- `omni_dst_kp_hourly_<slug>.csv`
- `omni_kp_3hour_<slug>.csv`

### 图像

保存在：

```text
OMNIdarw/outputs/figures/
```

生成文件名格式：

```text
omni_timeseries_<slug>.png
```

图中包含三幅共用时间轴的子图：

- `(a)` IMF Bz
- `(b)` Dst
- `(c)` Kp

## 运行方式

```powershell
cd D:\Desktop\lzt_thesis_code\OMNIdarw\scripts
python plot_omni_timeseries.py
```

运行后会在终端打印每个事件窗口对应的 CSV 与 PNG 路径。

## 脚本内部处理逻辑

1. 配置 Matplotlib 字体和论文风格
2. 对每个事件窗口发起 HAPI 请求
3. 将返回的 CSV 文本读入 `pandas`
4. 把缺测占位值替换为 `NaN`
5. 将 `KP1800` 编码转换为标准十进制 `Kp`
6. 额外生成 3 小时分辨率 `Kp` 数据表
7. 输出三联图

## 依赖

```powershell
pip install numpy pandas matplotlib
```

## 注意事项

- 该脚本依赖联网访问 CDAWeb
- 如果服务端返回 HAPI 错误文本，脚本会直接抛出异常
- 图题时间范围直接取自 `EventWindow`
- 输出目录会在运行时自动创建
