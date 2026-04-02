# GNSS 网格产品绘图模块

`GNSS_draw` 是一个基于 TOML 配置驱动的 netCDF 绘图模块，用于把 GNSS 电离层网格产品批量输出为论文风格地图。

当前实现面向三类数据：

- `VTEC`
- `dTEC`
- `ROTI`

## 模块职责

源码按照“配置 -> 读取 -> 预处理 -> 绘图 -> 批量调度”的链路拆分：

| 文件 | 作用 |
| --- | --- |
| `main.py` | 命令行入口，负责 `single` / `batch` 模式分发 |
| `config.py` | 解析 TOML 配置，生成类型化配置对象 |
| `reader.py` | 扫描 `.nc` 文件、识别变量名、读取指定时间切片 |
| `preprocess.py` | 经度归一化、区域裁剪、标题/文件名时间格式化 |
| `plotter.py` | 使用 Cartopy 和 Matplotlib 出图，可选叠加磁赤道 |
| `batch_export.py` | 单张输出、批量输出及输出路径组织 |

## 当前支持能力

- 单文件单时刻绘图
- 批量扫描多个 `.nc` 文件并导出所有时间切片
- `0~360` 与 `-180~180` 经度体系处理
- 预设区域：`global`、`asia_pacific`、`south_america`、`americas`
- 自定义区域：`plot.region = "custom"` 并配置 `[region.custom]`
- 为不同类别配置独立色标范围与配色
- 可选磁赤道叠加
- 多年份批处理

当前不包含：

- GUI
- GIF/MP4 合成
- 多面板拼图
- 事件级自动对比分析

## 运行方式

### 1. 单张绘图

```powershell
cd D:\Desktop\lzt_thesis_code\GNSSdraw
python -m GNSS_draw.main single --config GNSS_draw\config.example.toml
```

单张模式要求配置文件里提供：

- `[data].file`
- `timestamp` 或 `time_index`

### 2. 批量绘图

```powershell
cd D:\Desktop\lzt_thesis_code\GNSSdraw
python -m GNSS_draw.main batch --config GNSS_draw\config_vtec.toml
```

批量模式会：

1. 按类别和年份扫描数据目录
2. 逐文件识别时间轴
3. 顺序遍历所有时间切片
4. 对可绘制切片输出 PNG/JPG
5. 对空切片或裁剪后无数据的切片给出警告并跳过

## 配置文件

### 已提供的配置样例

| 文件 | 用途 |
| --- | --- |
| `config.example.toml` | 单张绘图样例 |
| `config.toml` | 简单批处理样例 |
| `config_vtec.toml` | VTEC 批处理 |
| `config_dtec.toml` | dTEC 批处理 |
| `config_roti.toml` | ROTI 批处理 |

### 关键配置节

#### `[data]`

| 字段 | 说明 |
| --- | --- |
| `root` | 数据根目录，通常指向 `../Data_download` |
| `year` | 单年批处理的默认年份 |
| `years` | 多年份批处理列表 |
| `category` | `VTEC` / `dTEC` / `ROTI` |
| `mode` | 可写 `single` 或 `batch`，CLI 会以命令行为准 |
| `file` | 单张模式输入文件 |
| `timestamp` | 优先按 UTC 时间戳选切片 |
| `time_index` | 若未给 `timestamp`，则按索引选切片 |
| `doys` | 只处理指定年积日目录 |

#### `[output]`

| 字段 | 说明 |
| --- | --- |
| `root` | 输出根目录 |
| `image_format` | `png`、`jpg`、`jpeg` |
| `dpi` | 输出分辨率 |

#### `[plot]`

| 字段 | 说明 |
| --- | --- |
| `region` | 预设区域名或 `custom` |
| `lon_mode` | `auto`、`-180_180`、`0_360` |
| `figure_size` | 图幅尺寸，单位英寸 |
| `font_family` | 首选字体族 |
| `show_magnetic_equator` | 是否绘制磁赤道 |
| `magnetic_equator_color` | 磁赤道线颜色 |
| `magnetic_equator_linewidth` | 磁赤道线宽 |

#### `[style.<category>]`

用于指定各类数据的：

- `cmap`
- `vmin`
- `vmax`

#### `[region.custom]`

仅在 `region = "custom"` 时启用，提供：

- `lon_min`
- `lon_max`
- `lat_min`
- `lat_max`

## 输出命名

输出路径格式固定为：

```text
outputs/<category>/<year>/<doy>/<category>_<timestamp>_<region>.<ext>
```

例如：

```text
outputs/VTEC/2024/130/VTEC_20240509T0010Z_americas.png
```

## 数据识别逻辑

`reader.py` 通过候选名称自动匹配变量：

- 时间：`time`
- 纬度：`lat`、`latitude`
- 经度：`lon`、`longitude`
- 数据变量：
  - `VTEC`：`atec`、`vtec`、`tec`
  - `dTEC`：`dtec`
  - `ROTI`：`roti`

如果文件结构不满足“一维经纬度 + 一维时间 + 三维数据变量”的假设，程序会报错并停止当前文件处理。

## 预处理规则

- `lon_mode = "auto"` 时，如果原始经度最大值大于 `180`，则自动按 `0~360` 处理
- 裁剪后若纬度或经度为空，直接报错
- 所有 `NaN` 会在绘图前被转成掩码，不参与着色
- 若裁剪后整张图没有有效值，批处理模式会记录警告并跳过

## 磁赤道绘制

当 `show_magnetic_equator = true` 时：

- 会尝试导入 `apexpy`
- 若未安装 `apexpy`，程序会给出警告，但继续输出地图
- 线的位置由给定时间附近的地磁场模型计算得到

## 建议工作流

1. 先用 `Data_download/download_nc_data.py` 下载数据
2. 用 `config.example.toml` 校验单张图是否正常
3. 复制或修改 `config_vtec.toml` / `config_dtec.toml` / `config_roti.toml`
4. 再进行整类、整年的批量导出
5. 如需并行补绘，可再使用 [../../run_logs/README.md](../../run_logs/README.md) 中的辅助脚本

## 依赖

```powershell
pip install xarray netCDF4 numpy pandas matplotlib cartopy
```

若启用磁赤道线，额外安装：

```powershell
pip install apexpy
```
