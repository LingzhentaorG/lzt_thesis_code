# 电离层与空间天气数据分析绘图工具集

本项目是一个用于电离层和空间天气数据分析的 Python 工具集，包含三个独立的子项目，分别用于处理 GNSS 电离层数据、GOLD 卫星数据和 OMNI 太阳风参数数据。

## 项目结构

```
lzt_thesis_code/
├── GNSSdraw/                 # GNSS 电离层数据绘图模块
│   ├── Data_download/        # 数据下载模块
│   │   └── download_nc_data.py
│   └── GNSS_draw/            # 核心绘图模块
│       ├── main.py           # 主入口程序
│       ├── config.py         # 配置解析模块
│       ├── plotter.py        # 绑图模块
│       ├── reader.py         # 数据读取模块
│       ├── preprocess.py     # 数据预处理模块
│       └── batch_export.py   # 批量导出模块
├── GOLDdraw/                 # GOLD 卫星数据处理模块
│   ├── gold_ni1_map_1356.py          # 主绘图脚本（散点图模式）
│   ├── gold_ni1_plot_stitched_v2.py  # 增强脚本（网格模式）
│   └── gold_ni1_plot_four_panel.py   # 四面板图脚本
├── OMNIdarw/                 # OMNI 太阳风参数绘图模块
│   ├── scripts/
│   │   └── plot_omni_timeseries.py   # 时间序列绘图脚本
│   └── outputs/              # 输出目录
│       ├── data/             # CSV 数据文件
│       └── figures/          # 图像文件
└── README.md                 # 本文件
```

---

## 一、GNSSdraw - GNSS 电离层数据绘图模块

### 1.1 功能简介

GNSSdraw 是一个用于读取和处理 GNSS 电离层 netCDF 数据的 Python 工具集，支持：

- **数据类型**：VTEC（垂直总电子含量）、dTEC（相对总电子含量）、ROTI（旋转指数）
- **绘图模式**：单文件单时刻绘图、批量遍历全年文件并导出
- **区域裁剪**：全球、亚太地区、南美洲、美洲、自定义区域
- **磁赤道叠加**：支持在图上绘制磁赤道线

### 1.2 数据来源

数据来自名古屋大学太阳地球环境研究所（ISEE）：

- VTEC: `https://stdb2.isee.nagoya-u.ac.jp/GPS/shinbori/AGRID2/nc/`
- dTEC: `https://stdb2.isee.nagoya-u.ac.jp/GPS/shinbori/GRID2/nc/`
- ROTI: `https://stdb2.isee.nagoya-u.ac.jp/GPS/shinbori/RGRID2/nc/`

### 1.3 环境要求

- Python 3.10+
- 依赖库：`xarray`, `netCDF4`, `numpy`, `pandas`, `matplotlib`, `cartopy`

```powershell
pip install xarray netCDF4 numpy pandas matplotlib cartopy
```

### 1.4 使用方法

#### 数据下载

```powershell
cd GNSSdraw/Data_download
python download_nc_data.py --root . --dates 2024-05-09 2024-05-10
```

**参数说明**：
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--root` | `.` | 项目根目录 |
| `--year` | `2024` | 年份 |
| `--doys` | `130 131 132 133 283 284 285 286` | 儒略日列表 |
| `--dates` | 无 | UTC 日期（YYYY-MM-DD 格式，优先于 --year 和 --doys） |
| `--workers` | `6` | 并行下载线程数 |
| `--force` | 否 | 强制覆盖已存在文件 |

#### 单张绘图

```powershell
cd GNSSdraw
python -m GNSS_draw.main single --config GNSS_draw\config.toml
```

#### 批量绘图

```powershell
cd GNSSdraw
python -m GNSS_draw.main batch --config GNSS_draw\config.toml
```

### 1.5 配置文件说明

配置文件采用 TOML 格式，示例如下：

```toml
[data]
root = "../Data_download"
year = "2024"
category = "VTEC"           # VTEC / dTEC / ROTI
mode = "single"             # single / batch
file = "../Data_download/VTEC_data/2024/130/2024050900_atec.nc"
timestamp = "2024-05-09T00:10:00Z"
doys = ["130"]

[output]
root = "./outputs"
image_format = "png"
dpi = 300

[plot]
region = "americas"         # global / asia_pacific / south_america / americas / custom
lon_mode = "auto"           # auto / -180_180 / 0_360
figure_size = [12.0, 6.75]
font_family = "Times New Roman"
show_magnetic_equator = true
magnetic_equator_color = "red"
magnetic_equator_linewidth = 1.5

[style.vtec]
cmap = "viridis"
vmin = 0
vmax = 80

[region.custom]
lon_min = -170
lon_max = -20
lat_min = -80
lat_max = 80
```

### 1.6 输出结构

```
outputs/
└── VTEC/
    └── 2024/
        └── 130/
            └── VTEC_20240509T0010Z_americas.png
```

---

## 二、GOLDdraw - GOLD 卫星数据处理模块

### 2.1 功能简介

GOLDdraw 用于处理 NASA GOLD（Global-scale Observations of the Limb and Disk）卫星的 NI1 级数据，主要功能：

- 读取 GOLD NI1 级 NetCDF 数据（135.6 nm 波长）
- 自动匹配 CHA（北半球）和 CHB（南半球）通道数据对
- 生成地理定位辐射亮度图像
- 叠加磁赤道线
- 支持多种可视化模式：单图、四面板图、网格合并图

**科学背景**：135.6 nm 是氧原子发射线，是研究热层和电离层的重要光谱特征，可用于分析电子密度分布、夜间电离层结构等。

### 2.2 数据来源

- [NASA GOLD 数据门户](https://gold.cs.ucf.edu/data/)
- [UCAR/NCAR 数据档案](https://www.ncei.noaa.gov/products/gold)

### 2.3 环境要求

- Python 3.10+
- 依赖库：`numpy`, `netCDF4`, `matplotlib`, `cartopy`, `apexpy`

```powershell
pip install numpy netCDF4 matplotlib cartopy apexpy
```

### 2.4 脚本说明

#### gold_ni1_map_1356.py - 主绘图脚本

批量处理 tar 文件并生成单张 PNG 图像（散点图模式）。

```powershell
python gold_ni1_map_1356.py <tar文件或目录> [选项]
```

**参数说明**：
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `inputs` | `.` | tar 文件或目录 |
| `--output-root` | `png_output` | 输出目录 |
| `--target-nm` | `135.6` | 目标波长 (nm) |
| `--max-pair-minutes` | `5.0` | CHA/CHB 配对最大时间差（分钟） |
| `--quality-mode` | `all` | 质量过滤模式：`all` / `good` |
| `--vmin` | `0.0` | 色标下限 (Rayleighs/nm) |
| `--vmax` | `300.0` | 色标上限 (Rayleighs/nm) |
| `--dpi` | `180` | 输出 DPI |
| `--extent` | `-105 15 -60 60` | 地图范围（西、东、南、北） |

#### gold_ni1_plot_stitched_v2.py - 增强版脚本

使用 pcolormesh 绘制更平滑的图像，支持两种合并模式：

- `native` 模式：保持原始数据网格
- `grid` 模式：重采样到规则经纬度网格

```powershell
python gold_ni1_plot_stitched_v2.py data.tar --merge-mode grid --grid-step 0.5
```

#### gold_ni1_plot_four_panel.py - 四面板图脚本

生成 2x2 四面板图像，适合对比不同时刻的观测数据。需在脚本中配置目标时间。

### 2.5 输出说明

**命名格式**：`<日期>T<时间>Z_CHA-<CHA时间>_CHB-<CHB时间>_<波长>nm.png`

示例：`20240508T2010Z_CHA-2010_CHB-2010_135p6nm.png`

---

## 三、OMNIdarw - OMNI 太阳风参数绘图模块

### 3.1 功能简介

OMNIdarw 用于从 NASA CDAWeb 获取 OMNI 太阳风参数数据，并生成适合论文使用的时间序列图：

- **IMF Bz**：行星际磁场 Bz 分量（1 分钟分辨率）
- **Dst 指数**：磁暴扰动时间指数（小时分辨率）
- **Kp 指数**：行星 Kp 指数（3 小时分辨率）

### 3.2 数据来源

通过 NASA CDAWeb HAPI 接口获取：
- Bz 数据：`OMNI_HRO2_1MIN` 数据集
- Dst/Kp 数据：`OMNI2_H0_MRG1HR` 数据集

### 3.3 环境要求

- Python 3.10+
- 依赖库：`numpy`, `pandas`, `matplotlib`

```powershell
pip install numpy pandas matplotlib
```

### 3.4 使用方法

```powershell
cd OMNIdarw/scripts
python plot_omni_timeseries.py
```

### 3.5 事件窗口配置

在脚本中定义事件窗口：

```python
EVENT_WINDOWS: tuple[EventWindow, ...] = (
    EventWindow("20240510_20240513", "2024-05-10T00:00:00Z", "2024-05-13T00:00:00Z"),
    EventWindow("20241010_20241013", "2024-10-10T00:00:00Z", "2024-10-13T00:00:00Z"),
    EventWindow("20241231_20250103", "2024-12-31T00:00:00Z", "2025-01-03T00:00:00Z"),
)
```

### 3.6 输出说明

**数据文件**：
- `omni_bz_1min_<slug>.csv`：IMF Bz 1 分钟数据
- `omni_dst_kp_hourly_<slug>.csv`：Dst/Kp 小时数据
- `omni_kp_3hour_<slug>.csv`：Kp 3 小时数据

**图像文件**：
- `omni_timeseries_<slug>.png`：三面板时间序列图

---

## 四、通用依赖安装

```powershell
pip install xarray netCDF4 numpy pandas matplotlib cartopy apexpy
```

---

## 五、项目特点

1. **统一风格**：所有模块均采用论文级别的图像输出标准，支持 Times New Roman 字体
2. **灵活配置**：支持通过配置文件或命令行参数进行定制
3. **批量处理**：支持批量处理大量数据文件
4. **科学可视化**：支持磁赤道线叠加、地理投影、统一色标等专业功能

---

## 六、参考文献

- [NASA GOLD Mission](https://gold.cs.ucf.edu/)
- [NASA CDAWeb](https://cdaweb.gsfc.nasa.gov/)
- [名古屋大学 ISEE GNSS-TEC 数据库](https://stdb2.isee.nagoya-u.ac.jp/)
- [ApexPy Documentation](https://apexpy.readthedocs.io/)

---

## 七、许可证

本项目仅供科研和教育用途。
