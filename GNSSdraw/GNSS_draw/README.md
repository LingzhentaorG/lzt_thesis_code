# GNSS `nc` 绘图程序

该程序用于读取 `VTEC`、`dTEC`、`ROTI` 三类 netCDF 文件，并输出适合论文插图的电离层地图。

## 功能范围

- 单文件单时刻绘图
- 批量遍历全年 `nc` 文件并导出全部时刻图片
- 区域裁剪：`global`、`asia_pacific`、`south_america`、`americas`、`custom`
- 统一英文标题、统一命名、终端日志输出

当前版本不包含拼图对比、GIF/MP4 或 GUI。

## 环境要求

- Python 3.10+
- 已安装依赖：
  - `xarray`
  - `netCDF4`
  - `numpy`
  - `pandas`
  - `matplotlib`
  - `cartopy`

示例安装命令：

```powershell
pip install xarray netCDF4 numpy pandas matplotlib cartopy
```

## 配置文件

示例配置位于 [config.example.toml](/D:/Desktop/GNSSdraw/GNSS_draw/config.example.toml)。

关键字段：

- `[data]`
  - `root`: 数据根目录，默认相对配置文件解析
  - `year`: 年份目录，如 `2024`
  - `category`: `VTEC` / `dTEC` / `ROTI`
  - `file`: `single` 模式必须提供
  - `timestamp`: 优先于 `time_index`
  - `doys`: `batch` 模式可选，仅处理指定儒略日
- `[output]`
  - `root`: 输出目录
  - `image_format`: `png` / `jpg`
  - `dpi`: 输出分辨率
- `[plot]`
  - `region`: `global` / `asia_pacific` / `south_america` / `americas` / `custom`
  - `lon_mode`: `auto` / `-180_180` / `0_360`
  - `figure_size`: 图像尺寸
  - `font_family`: 字体优先级
- `[style.<category>]`
  - `cmap`, `vmin`, `vmax`
- `[region.custom]`
  - 自定义区域坐标

## 运行方式

从项目根目录 [D:/Desktop/GNSSdraw](/D:/Desktop/GNSSdraw) 执行。

单张导图：

```powershell
python -m GNSS_draw.main single --config D:\Desktop\GNSSdraw\GNSS_draw\config.example.toml
```

批量导图：

```powershell
python -m GNSS_draw.main batch --config D:\Desktop\GNSSdraw\GNSS_draw\config.example.toml
```

## 输出结构

输出目录结构如下：

```text
outputs/
  VTEC/
    2024/
      130/
        VTEC_20240509T0010Z_americas.png
```

## 默认图像规则

- 标题格式：`{CATEGORY} Map YYYY-MM-DD HH:MM UTC`
- 默认字体优先：`Times New Roman`
- 默认区域：`americas`，范围 `lon -170~-20`、`lat -80~80`
- 默认配色：
  - `VTEC`: `viridis`, `0~80`
  - `dTEC`: `viridis`, `-0.4~0.4`
  - `ROTI`: `viridis`, `0~1`

## 异常处理

程序会对以下情况输出明确错误或警告：

- 输入文件不存在
- 数据目录为空
- netCDF 文件无法读取
- 未识别出时间、经纬度或数据变量
- 指定时间不存在
- 裁剪后无有效数据
- 输出目录无法创建
