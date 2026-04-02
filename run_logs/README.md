# GNSS 并行重绘与补绘脚本

`run_logs` 目录中既有运行日志，也有两个为当前工作站准备的 GNSS 并行脚本。

## 脚本清单

| 文件 | 作用 |
| --- | --- |
| `gnss_full_redraw.py` | 全量并行扫描所有 GNSS 数据目录，对缺失图片执行重绘 |
| `gnss_parallel_fill.py` | 基于时间阈值补绘旧图或缺图 |
| `*.out.log` / `*.err.log` | 对应脚本的标准输出与错误输出日志 |

## 1. `gnss_full_redraw.py`

这个脚本会：

1. 读取 `config_vtec.toml`、`config_dtec.toml`、`config_roti.toml`
2. 枚举每个类别下所有年份和年积日目录
3. 建立并行任务
4. 逐时间切片检查目标输出是否存在
5. 缺图时调用 `GNSS_draw.batch_export.render_slice` 进行渲染

它的特点是：

- 优先补齐“还没有生成”的图
- 已存在文件直接跳过
- 使用 `ProcessPoolExecutor` 并发处理不同年积日任务

## 2. `gnss_parallel_fill.py`

这个脚本和全量重绘的区别在于，它除了检查“文件是否存在”，还会检查输出文件修改时间：

- 如果输出文件存在，且修改时间不早于当前类别对应的阈值时间，则跳过
- 如果输出文件不存在，或存在但时间早于阈值，则重新渲染

这适用于“配置调整之后只重绘旧图”的场景。

### 阈值来源

阈值写死在脚本中的 `THRESHOLDS` 常量里，当前是绝对时间戳对应的 `datetime`。如果你重新做了一轮批量输出，希望下一次只补绘更旧文件，需要手工更新这里。

## 使用前提

这两个脚本都不是通用工具，运行前默认满足以下条件：

- 仓库绝对路径为 `D:\Desktop\lzt_thesis_code`
- `GNSSdraw\GNSS_draw\config_*.toml` 已配置完成
- `GNSSdraw\Data_download` 下已经存在需要处理的 `.nc` 数据

如果仓库移动到别的位置，需要先修改脚本中的 `ROOT` 常量。

## 运行方式

```powershell
cd D:\Desktop\lzt_thesis_code\run_logs
python gnss_full_redraw.py
```

```powershell
cd D:\Desktop\lzt_thesis_code\run_logs
python gnss_parallel_fill.py
```

## 结果与日志

脚本运行时会打印：

- 每个任务完成时的类别、年份、年积日
- 当前批次新生成数量
- 跳过数量
- 按类别汇总的统计结果

如果需要留档，可以把输出重定向到 `*.out.log` 和 `*.err.log`。

## 建议

- 首次全量出图时，优先运行 `gnss_full_redraw.py`
- 修改了配色、区域或磁赤道参数后，如只想补绘旧图，可运行 `gnss_parallel_fill.py`
- 若只是需要常规批处理，优先使用 [../GNSSdraw/GNSS_draw/README.md](../GNSSdraw/GNSS_draw/README.md) 中的标准入口，而不是这里的运维脚本
