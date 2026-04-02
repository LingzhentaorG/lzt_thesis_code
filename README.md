# 电离层与空间天气论文绘图项目

本仓库收集了论文写作中使用的三类数据处理与制图脚本：

- `GNSSdraw`：下载并绘制 GNSS 电离层网格产品，支持 `VTEC`、`dTEC`、`ROTI`
- `GOLDdraw`：读取 NASA GOLD NI1 归档文件，生成 135.6 nm 辐亮度地图
- `OMNIdarw`：从 NASA CDAWeb HAPI 接口下载 OMNI 参数，输出 CSV 与时间序列图
- `run_logs`：面向本机批处理的 GNSS 并行重绘/补绘脚本与运行日志

项目整体偏向“论文生产工具箱”而非通用 Python 包：源码可复用，但部分脚本仍保留了针对当前数据目录和工作站环境的硬编码设置。

## 仓库结构

```text
lzt_thesis_code/
├── GNSSdraw/
│   ├── Data_download/
│   │   ├── download_nc_data.py
│   │   ├── README.md
│   │   ├── VTEC_data/
│   │   ├── dTEC_data/
│   │   └── ROTI_data/
│   └── GNSS_draw/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
│       ├── reader.py
│       ├── preprocess.py
│       ├── plotter.py
│       ├── batch_export.py
│       ├── README.md
│       ├── config.example.toml
│       ├── config.toml
│       ├── config_vtec.toml
│       ├── config_dtec.toml
│       └── config_roti.toml
├── GOLDdraw/
│   ├── gold_ni1_map_1356.py
│   ├── gold_ni1_plot_stitched_v2.py
│   ├── gold_ni1_plot_four_panel.py
│   └── README.md
├── OMNIdarw/
│   ├── scripts/
│   │   └── plot_omni_timeseries.py
│   ├── outputs/
│   │   ├── data/
│   │   └── figures/
│   └── README.md
├── run_logs/
│   ├── gnss_full_redraw.py
│   ├── gnss_parallel_fill.py
│   ├── *.out.log / *.err.log
│   └── README.md
└── README.md
```

## 模块概览

### 1. GNSSdraw

`GNSSdraw` 分成两个部分：

- `Data_download/download_nc_data.py`
  从名古屋大学 ISEE 数据站批量抓取 `VTEC`、`dTEC`、`ROTI` 的 `.nc` 文件
- `GNSS_draw/`
  读取下载后的 netCDF 网格文件，按配置输出单张或批量地图

GNSS 绘图链路如下：

```text
远程目录索引 -> 本地 nc 数据目录 -> 配置解析 -> 读取时间切片 -> 经度/区域预处理 -> Cartopy 出图
```

当前实现支持：

- 自动识别时间、纬度、经度和主要数据变量
- `single` 与 `batch` 两种导出模式
- 预设区域与自定义区域裁剪
- `0~360` / `-180~180` 经度体系转换
- 可选磁赤道叠加
- 多年份批量扫描

详细说明见：

- [GNSSdraw/Data_download/README.md](GNSSdraw/Data_download/README.md)
- [GNSSdraw/GNSS_draw/README.md](GNSSdraw/GNSS_draw/README.md)

### 2. GOLDdraw

`GOLDdraw` 直接读取 `.tar` 归档中的 GOLD NI1 NetCDF 文件，不要求先手工解压。核心流程是：

1. 扫描归档内文件名
2. 自动匹配同日且时间接近的 `CHA` / `CHB` 观测对
3. 读取 `REFERENCE_POINT_LAT/LON`、`WAVELENGTH`、`RADIANCE`、`QUALITY_FLAG`
4. 抽取 135.6 nm 辐亮度
5. 按不同脚本输出散点图、拼接图或四面板图

三个脚本的定位分别是：

- `gold_ni1_map_1356.py`：散点模式，适合快速批量出图
- `gold_ni1_plot_stitched_v2.py`：保留原始扫描条带或重采样到规则网格，适合正式作图
- `gold_ni1_plot_four_panel.py`：固定时间列表的四面板论文图

详细说明见 [GOLDdraw/README.md](GOLDdraw/README.md)。

### 3. OMNIdarw

目录名 `OMNIdarw` 沿用了仓库原始拼写。该模块通过 CDAWeb HAPI 接口抓取：

- `OMNI_HRO2_1MIN` 中的 `BZ_GSM`
- `OMNI2_H0_MRG1HR` 中的 `DST1800` 与 `KP1800`

脚本会把事件窗口内的数据落盘为 CSV，并生成一张三联图：

- `(a)` IMF Bz
- `(b)` Dst
- `(c)` Kp

详细说明见 [OMNIdarw/README.md](OMNIdarw/README.md)。

### 4. run_logs

`run_logs` 里既有运行日志，也有两个辅助批处理脚本：

- `gnss_full_redraw.py`：全量并行重绘，已存在输出时直接跳过
- `gnss_parallel_fill.py`：按时间阈值补绘“旧图”或“缺图”

这两个脚本依赖当前仓库的绝对路径与现有配置文件，属于本机运维脚本，不是通用 CLI 工具。详细说明见 [run_logs/README.md](run_logs/README.md)。

## 运行环境

建议使用 Python 3.10 及以上版本。由于 `cartopy`、`apexpy` 等地学绘图库安装方式与平台相关，仓库没有提供统一的 `requirements.txt`，建议按模块安装。

常见依赖如下：

```powershell
pip install numpy pandas matplotlib xarray netCDF4 cartopy apexpy
```

如果只运行 OMNI 脚本，可最小安装：

```powershell
pip install numpy pandas matplotlib
```

## 快速开始

### GNSS 数据下载

```powershell
cd D:\Desktop\lzt_thesis_code\GNSSdraw\Data_download
python download_nc_data.py --root . --dates 2024-05-09 2024-05-10
```

### GNSS 单张绘图

```powershell
cd D:\Desktop\lzt_thesis_code\GNSSdraw
python -m GNSS_draw.main single --config GNSS_draw\config.example.toml
```

### GNSS 批量绘图

```powershell
cd D:\Desktop\lzt_thesis_code\GNSSdraw
python -m GNSS_draw.main batch --config GNSS_draw\config_vtec.toml
```

### GOLD 批量出图

```powershell
cd D:\Desktop\lzt_thesis_code\GOLDdraw
python gold_ni1_plot_stitched_v2.py . --merge-mode native --output-root png_output
```

### OMNI 三联图

```powershell
cd D:\Desktop\lzt_thesis_code\OMNIdarw\scripts
python plot_omni_timeseries.py
```

## 数据与输出目录

仓库中已经包含大量样例数据和产出结果，典型结构如下：

- `GNSSdraw/Data_download/*_data/<year>/<doy>/*.nc`
- `GNSSdraw/GNSS_draw/outputs/<category>/<year>/<doy>/*.png`
- `GOLDdraw/png_output/<tar-name>/*.png`
- `GOLDdraw/four_panel_output/*.png`
- `OMNIdarw/outputs/data/*.csv`
- `OMNIdarw/outputs/figures/*.png`

这些目录主要用于论文作图复现和结果留档。

## 文档索引

- [GNSS 下载说明](GNSSdraw/Data_download/README.md)
- [GNSS 绘图说明](GNSSdraw/GNSS_draw/README.md)
- [GOLD 脚本说明](GOLDdraw/README.md)
- [OMNI 脚本说明](OMNIdarw/README.md)
- [批处理脚本说明](run_logs/README.md)

## 注意事项

- 这不是一个经过包装发布的 Python 包，默认工作方式是“在仓库目录中直接运行脚本”。
- `run_logs` 下的辅助脚本写死了绝对路径，如果仓库移动位置，需要同步修改。
- `gold_ni1_plot_four_panel.py` 当前仍通过脚本内部变量指定输入 tar 包、目标时刻和输出路径。
- `GNSS_draw` 的批量模式会在遇到空切片或裁剪后无有效值时记录警告并跳过，不会中断整批任务。
- 仓库中的文档现在以“当前已实现行为”为准，不再保留过时的需求文档。
