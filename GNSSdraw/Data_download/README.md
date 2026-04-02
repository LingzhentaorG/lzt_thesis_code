# GNSS 数据下载模块

本目录负责从名古屋大学 ISEE GNSS-TEC 数据站批量下载 `.nc` 文件，为后续 `GNSS_draw` 绘图模块提供输入数据。

当前唯一脚本是 [download_nc_data.py](download_nc_data.py)。

## 支持的数据源

脚本内置了三类源地址：

| 类别 | 远程目录 |
| --- | --- |
| `VTEC` | `https://stdb2.isee.nagoya-u.ac.jp/GPS/shinbori/AGRID2/nc/{year}/` |
| `dTEC` | `https://stdb2.isee.nagoya-u.ac.jp/GPS/shinbori/GRID2/nc/{year}/` |
| `ROTI` | `https://stdb2.isee.nagoya-u.ac.jp/GPS/shinbori/RGRID2/nc/{year}/` |

默认年积日列表是：

```text
130, 131, 132, 133, 283, 284, 285, 286
```

## 下载结果目录

脚本会把三类数据分别保存到：

```text
Data_download/
├── VTEC_data/<year>/<doy>/*.nc
├── dTEC_data/<year>/<doy>/*.nc
└── ROTI_data/<year>/<doy>/*.nc
```

目录会自动创建，不需要手工预先建立。

## 运行方式

在本目录执行：

```powershell
python download_nc_data.py --root .
```

或者在仓库根目录执行：

```powershell
python GNSSdraw\Data_download\download_nc_data.py --root GNSSdraw\Data_download
```

## 常用参数

| 参数 | 说明 |
| --- | --- |
| `--root` | 下载根目录，三类输出子目录会在该目录下创建 |
| `--year` | 年份，和 `--doys` 搭配使用 |
| `--doys` | 年积日列表，例如 `130 131 132` |
| `--dates` | 直接给 UTC 日期，格式为 `YYYY-MM-DD`，会覆盖 `--year` 和 `--doys` |
| `--workers` | 并发下载线程数 |
| `--force` | 已存在文件也重新下载 |

### 示例 1：按默认年积日下载 2024 年数据

```powershell
python download_nc_data.py --root . --year 2024
```

### 示例 2：按真实日期下载

```powershell
python download_nc_data.py --root . --dates 2024-05-09 2024-05-10 2025-01-01
```

### 示例 3：提高并发并覆盖旧文件

```powershell
python download_nc_data.py --root . --year 2024 --doys 130 131 --workers 10 --force
```

## 实现要点

- 先访问每个年积日目录的 HTML 页面，解析其中所有 `.nc` 链接
- 为每个目标文件生成下载任务
- 使用线程池并发下载
- 下载时先写入 `.part` 临时文件，完成后再原子替换为正式文件
- 对单个文件失败执行最多 3 次重试
- 已存在且文件大小大于 0 的目标会直接跳过

## 终端输出说明

脚本会打印：

- 每类数据计划下载的文件数量
- 每个文件的下载结果：`[DOWNLOADED]`、`[SKIPPED]`、`[FAILED]`
- 最终统计：下载成功、跳过、失败与总任务数

如果远程目录无法访问，会直接终止并返回错误码。

## 与 GNSS 绘图模块的关系

下载完成后，可直接把 `Data_download` 目录作为 `GNSS_draw` 配置中的 `[data].root` 输入。详见 [../GNSS_draw/README.md](../GNSS_draw/README.md)。
