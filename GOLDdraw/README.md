# GOLD NI1 Map 135.6

从 NASA GOLD 卫星 NI1 级数据生成 135.6 nm 波长地理定位图像的 Python 工具集。

## 项目简介

本项目用于处理 NASA GOLD (Global-scale Observations of the Limb and Disk) 卫星的 NI1 级数据。GOLD 是一颗地球同步卫星，观测热层和电离层的远紫外辐射。本工具能够：

- 直接从 `.tar` 归档文件中读取 NetCDF 格式的 GOLD NI1 数据
- 自动匹配 CHA（北半球）和 CHB（南半球）通道的观测数据对
- 生成 135.6 nm 波长的地理定位辐射亮度图像
- 绘制磁赤道线，辅助电离层研究
- 支持多种可视化模式：单图、四面板图、网格合并图

**135.6 nm** 是氧原子发射线，是研究热层和电离层的重要光谱特征，可用于分析电子密度分布、夜间电离层结构等。

## 功能特性

- **自动配对匹配**：根据观测时间自动匹配 CHA 和 CHB 通道数据
- **灵活的质量控制**：支持按质量标志过滤像素
- **可定制输出**：可调整色标范围、图像尺寸、DPI 等参数
- **批量处理**：支持处理多个 tar 文件或包含 tar 文件的目录
- **地理投影**：使用 Cartopy 生成带海岸线和边界线的地图
- **磁赤道叠加**：使用 ApexPy 计算并绘制磁赤道线
- **多种绘图模式**：支持散点图、网格图、四面板图等多种输出格式

## 环境要求

- Python 3.10+
- 依赖库：
  - `numpy`
  - `netCDF4`
  - `matplotlib`
  - `cartopy`
  - `apexpy`

安装依赖：

```bash
pip install numpy netCDF4 matplotlib cartopy apexpy
```

## 脚本说明

### 1. gold_ni1_map_1356.py

主脚本，批量处理 tar 文件并生成单张 PNG 图像。使用散点图方式绘制数据。

**特点**：
- 批量处理多个 tar 归档文件
- 自动发现并匹配 CHA/CHB 数据对
- 叠加磁赤道线
- 输出独立的 PNG 文件

**使用方法**：

```bash
python gold_ni1_map_1356.py <tar文件或目录> [选项]
```

**命令行参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `inputs` | `.` | 一个或多个 `.tar` 文件或包含 `.tar` 文件的目录 |
| `--output-root` | `png_output` | PNG 输出目录 |
| `--target-nm` | `135.6` | 目标波长 (nm) |
| `--max-pair-minutes` | `5.0` | CHA/CHB 配对的最大时间差（分钟） |
| `--quality-mode` | `all` | 质量过滤模式：`all` 保留所有有效像素，`good` 仅保留质量标志为 0 的像素 |
| `--vmin` | `0.0` | 色标下限 (Rayleighs/nm) |
| `--vmax` | `300.0` | 色标上限 (Rayleighs/nm) |
| `--dpi` | `180` | 输出 DPI |
| `--figsize` | `7.2 5.8` | 图像尺寸（英寸） |
| `--point-size` | `9.0` | 散点大小 |
| `--extent` | `-105 15 -60 60` | 地图范围（西、东、南、北，单位：度） |
| `--limit` | 无 | 仅处理前 N 个配对 |
| `--verbose` | 否 | 打印每个生成的 PNG 文件路径 |

**示例**：

```bash
# 处理单个 tar 文件
python gold_ni1_map_1356.py NI2024050820240514.tar

# 处理多个 tar 文件
python gold_ni1_map_1356.py NI2024050820240514.tar NI2024100820241014.tar

# 处理目录中的所有 tar 文件
python gold_ni1_map_1356.py /path/to/data/ --output-root my_output

# 仅处理高质量数据并调整色标
python gold_ni1_map_1356.py data.tar --quality-mode good --vmin 10 --vmax 200
```

### 2. gold_ni1_plot_stitched_v2.py

增强版脚本，支持两种合并模式，使用 pcolormesh 绘制更平滑的图像。

**特点**：
- `native` 模式：保持原始数据网格，分别绘制两个半球
- `grid` 模式：将数据重采样到规则经纬度网格
- 使用 pcolormesh 绘制连续色块，视觉效果更佳
- 智能间隙检测，避免连接不连续的数据区域

**额外参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--merge-mode` | `native` | 合并模式：`native` 保持原始网格，`grid` 重采样到规则网格 |
| `--gap-factor` | `6.0` | 间隙检测因子，值越大越不敏感 |
| `--grid-step` | `0.25` | 网格模式下网格间距（度） |

**示例**：

```bash
# 使用原始网格模式
python gold_ni1_plot_stitched_v2.py data.tar --merge-mode native

# 使用规则网格模式，网格间距 0.5 度
python gold_ni1_plot_stitched_v2.py data.tar --merge-mode grid --grid-step 0.5
```

### 3. gold_ni1_plot_four_panel.py

生成 2x2 四面板图像，适合对比不同时刻的观测数据。

**特点**：
- 在一张图中展示四个时刻的数据
- 统一色标，便于对比
- 适合论文和报告使用

**使用方法**：

需要修改脚本中的配置参数：

```python
tar_path = Path(r"d:\Desktop\GOLDdraw\NI2024100820241014.tar")

target_times = [
    datetime(2024, 10, 10, 23, 52),
    datetime(2024, 10, 11, 0, 22),
    datetime(2024, 10, 12, 0, 22),
    datetime(2024, 10, 9, 0, 23),
]

output_path = output_dir / "four_panel_135p6nm.png"
```

然后运行：

```bash
python gold_ni1_plot_four_panel.py
```

## 输出说明

### 单图输出命名格式

```
<日期>T<时间>Z_CHA-<CHA时间>_CHB-<CHB时间>_<波长>nm.png
```

示例：`20240508T2010Z_CHA-2010_CHB-2010_135p6nm.png`

### 输出图像内容

- 地理坐标投影地图
- 海岸线和国界
- 经纬度网格
- 135.6 nm 辐射亮度伪彩色图
- 磁赤道线（红色虚线）
- 辐射亮度色标（单位：Rayleighs/nm）

## 项目结构

```
GOLDdraw/
├── gold_ni1_map_1356.py          # 主脚本（散点图模式）
├── gold_ni1_plot_stitched_v2.py  # 增强脚本（网格模式）
├── gold_ni1_plot_four_panel.py   # 四面板图脚本
├── png_output/                   # 默认输出目录
│   └── <tar文件名>/              # 每个 tar 文件对应一个子目录
│       └── *.png                 # 生成的图像文件
├── four_panel_output/            # 四面板图输出目录
│   └── four_panel_135p6nm.png    # 四面板图示例
├── NI*.tar                       # GOLD NI1 数据归档文件
├── .gitignore                    # Git 忽略配置
└── README.md                     # 本文件
```

## 数据来源

GOLD NI1 数据来自 NASA GOLD 任务，可从以下渠道获取：

- [NASA GOLD 数据门户](https://gold.cs.ucf.edu/data/)
- [UCAR/NCAR 数据档案](https://www.ncei.noaa.gov/products/gold)

## 技术细节

### 数据格式

GOLD NI1 数据为 NetCDF4 格式，主要变量包括：

| 变量名 | 说明 |
|--------|------|
| `REFERENCE_POINT_LAT` | 观测点纬度 |
| `REFERENCE_POINT_LON` | 观测点经度 |
| `WAVELENGTH` | 波长数组 |
| `RADIANCE` | 辐射亮度 |
| `QUALITY_FLAG` | 质量标志（0 表示高质量） |

### CHA/CHB 通道

- **CHA**：北半球通道
- **CHB**：南半球通道

两个通道的观测时间通常接近但不完全相同，脚本会自动匹配时间差在阈值内的数据对。

### 磁赤道计算

使用 ApexPy 库计算磁赤道位置，基于 IGRF 地磁场模型。磁赤道是磁纬度为 0° 的连线，对研究赤道异常（Equatorial Anomaly）现象非常重要。

## 许可证

本项目仅供科研和教育用途。

## 参考资料

- [NASA GOLD Mission](https://gold.cs.ucf.edu/)
- [GOLD Data Documentation](https://gold.cs.ucf.edu/documentation/)
- [ApexPy Documentation](https://apexpy.readthedocs.io/)
