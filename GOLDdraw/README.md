# GOLD NI1 制图脚本

本目录包含针对 NASA GOLD NI1 级数据的 135.6 nm 绘图脚本。输入通常是 `.tar` 归档文件，脚本会直接从归档内读取 NetCDF 数据，不要求先解压到磁盘。

## 数据处理思路

三个脚本共用一套核心思路：

1. 根据归档内文件名识别 `CHA` 与 `CHB` 两个观测通道
2. 按观测时间自动匹配成对数据
3. 从 `WAVELENGTH` 中选择最接近 135.6 nm 的波段
4. 读取对应的辐亮度、经纬度与质量标志
5. 绘制地理投影图，并叠加磁赤道

## 脚本对比

| 脚本 | 主要用途 | 典型场景 |
| --- | --- | --- |
| `gold_ni1_map_1356.py` | 散点批量出图 | 快速浏览和批量导图 |
| `gold_ni1_plot_stitched_v2.py` | 条带拼接 / 规则网格重采样 | 正式论文图、视觉效果更平滑 |
| `gold_ni1_plot_four_panel.py` | 固定 4 个时刻的四面板图 | 指定事件对比图 |

## 1. `gold_ni1_map_1356.py`

这是最直接的批处理脚本。它会：

- 扫描输入的 `.tar` 文件或目录
- 找出可配对的 `CHA` / `CHB` 文件
- 提取有效像素
- 以散点图方式输出单张地图

### 常用命令

```powershell
python gold_ni1_map_1356.py NI2024050820240514.tar
```

```powershell
python gold_ni1_map_1356.py . --output-root png_output --quality-mode good
```

### 重要参数

| 参数 | 说明 |
| --- | --- |
| `inputs` | 一个或多个 `.tar` 文件，或包含 `.tar` 的目录 |
| `--output-root` | 输出目录 |
| `--target-nm` | 目标波长，默认 `135.6` |
| `--max-pair-minutes` | `CHA/CHB` 最大允许配对时间差 |
| `--quality-mode` | `all` 保留全部有限值；`good` 仅保留 `QUALITY_FLAG == 0` |
| `--vmin` / `--vmax` | 色标范围 |
| `--figsize` | 图幅尺寸 |
| `--point-size` | 散点大小 |
| `--extent` | 地图显示范围 |
| `--limit` | 每个归档最多处理多少个配对 |

## 2. `gold_ni1_plot_stitched_v2.py`

这个脚本比散点版更适合正式作图，主要改进有：

- 支持保留原始扫描条带拓扑结构
- 支持把两条观测带重采样到规则经纬度网格
- 能容忍部分截断的 `.tar` 文件，只使用可读成员继续处理

### 两种拼接模式

#### `--merge-mode native`

- 逐条带使用 `pcolormesh`
- 保留原始观测几何
- 通过相邻网格距离阈值屏蔽不连续单元，避免跨越空洞连线

#### `--merge-mode grid`

- 把两条带上的有效像素投到规则经纬度网格
- 对同一网格单元取平均值
- 适合得到更连续、更平滑的整体图像

### 常用命令

```powershell
python gold_ni1_plot_stitched_v2.py . --merge-mode native
```

```powershell
python gold_ni1_plot_stitched_v2.py . --merge-mode grid --grid-step 0.5
```

### 补充参数

| 参数 | 说明 |
| --- | --- |
| `--gap-factor` | 条带模式下的间隙判定阈值倍数 |
| `--merge-mode` | `native` 或 `grid` |
| `--grid-step` | 规则网格步长，单位度 |

## 3. `gold_ni1_plot_four_panel.py`

这是一个更偏“项目内定制”的论文脚本。特点是：

- 不走命令行参数
- 在脚本内部写死输入 tar 包、目标时刻、输出路径
- 输出一张 2x2 四面板图

当前适用于“已经确定要展示哪 4 个时刻”的情形。修改方式主要是编辑：

- `tar_path`
- `target_times`
- `output_path`

运行方式：

```powershell
python gold_ni1_plot_four_panel.py
```

## 输出命名

单图输出文件名格式：

```text
YYYYMMDDTHHMMZ_CHA-HHMM_CHB-HHMM_135p6nm.png
```

例如：

```text
20240508T2010Z_CHA-2010_CHB-2010_135p6nm.png
```

默认目录结构：

```text
png_output/<tar文件名去扩展名>/*.png
```

四面板图则输出到脚本指定目录，例如 `four_panel_output/four_panel_135p6nm.png`。

## 依赖

```powershell
pip install numpy netCDF4 matplotlib cartopy apexpy
```

## 使用建议

- 需要快速全量浏览时，优先用 `gold_ni1_map_1356.py`
- 需要更平滑、可发表的拼接效果时，用 `gold_ni1_plot_stitched_v2.py`
- 需要固定 4 个关键时刻的版式图时，用 `gold_ni1_plot_four_panel.py`

## 注意事项

- 代码默认处理的是 GOLD `NI1` 产品
- 三个脚本都假定输入文件名符合官方命名规则，否则无法识别观测时刻
- `gold_ni1_plot_four_panel.py` 中的路径目前是本机硬编码，需要按实际环境修改
