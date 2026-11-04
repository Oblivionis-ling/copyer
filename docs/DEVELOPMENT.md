# 开发与构建


开发环境：Windows 10/11、Python 3.11、PySide6 Essentials。使用项目内 Conda 环境：

```powershell
conda create -y -p .\.conda_env python=3.11 pip
$env:PYTHONNOUSERSITE = '1'
.\.conda_env\python.exe -B -m pip install --no-cache-dir --no-compile -r requirements.txt
.\.conda_env\python.exe -B tools\fetch_exiftool.py
.\.conda_env\python.exe -B copyer.py
```

测试及打包：

```powershell
$env:PYTHONNOUSERSITE = '1'
.\.conda_env\python.exe -B -m unittest discover -s tests -v
.\.conda_env\python.exe -B tools\verify_update_installer.py
.\.conda_env\python.exe -B tools\benchmark_scan.py --cache
.\build_copyer.ps1
```

构建脚本使用 `.conda_env\python.exe` 并隔离 DLL 搜索路径。`copyer.spec` 从 `copyer_version.py` 读取版本，生成 `dist/copyer-1.5.3/`。首次构建会下载固定版本的 ExifTool，并校验官方 SHA-256；也可以用 `tools/fetch_exiftool.py --archive 下载好的ZIP` 离线准备。源码仓库不提交环境、第三方二进制、构建输出和便携压缩包。

## 本地保持精简

- 保留源码、资源、测试、`.conda_env` 和 `vendor/exiftool`，日常直接从源码运行。
- `requirements.txt` 使用 Essentials，覆盖界面与 QtTest；不安装完整 PySide6 或 Addons。Ruff、QtAwesome 和 QtPy 按需安装，不作为日常依赖。
- `dist/Copyer-v1.5.3-Windows-x64.zip` 为当前分发包，与同目录的 SHA256SUMS 一并发布到 GitHub Release；旧的 v1.5.2 正式分发 ZIP 保留。构建脚本只生成本地文件，不自动上传。
- `build/`、`_work/` 是可重建输出，验证后可清理；界面截图统一写入 `_work/ui/`。分发包完整解压后运行 `Copyer.exe`。
- `-B` 和构建脚本避免生成 Python 字节码缓存。调试符号 `.pdb` 可移除；保留 Python 标准库、包元数据、Qt 类型提示及第三方许可。
- ExifTool 保留解析器和运行库，省去独立手册、交互式启动器及地理数据库。历史设计资料保留在 [GitHub 设计档案](https://github.com/Oblivionis-ling/copyer/tree/main/docs/design)。

## 验证与项目结构

- `copyer.py`：应用入口。
- `copyer_ui.py`：原生 Qt 界面、主窗口内的设置页和任务状态；主页面统一采用紧凑布局，不加载媒体预览。
- `copyer_materials.py`：中性方格、控件折射和透明窗框绘制。
- `copyer_core.py`：扫描、计划、复制、校验和校验后的源文件删除，不依赖界面。
- `copyer_metadata.py`：RAW / 照片 / 视频日期选择、时区策略与后台读取进程。
- `copyer_update.py`：GitHub 正式版查询、下载校验、解压与 Windows 替换/回退助手。
- `tests/`：文件异常、取消、重试、线程生命周期和界面交互测试。
- `tools/capture_ui.py` / `tools/capture_states.py`：隔离测试媒体及 Qt 界面截图，不写入正式用户设置。
- [第三方组件与来源](../THIRD_PARTY.md)。
- [更新记录](../CHANGELOG.md)。

v1.5.3 增加完整性删除、更新、批量日期与缓存回归测试；真实符号链接测试在 Windows 权限不足时跳过。包含 10 种 RAW 的真实元数据样本，以及 HEIF、Apple/DJI 字段、跨日时区、超时与取消测试。测试样本保留元数据，并非完整可解码的原片；支持列表不代表每款相机都做过实机验证。读卡器热拔插和掉电恢复尚未验证。

## 更新与清理边界

- 正式更新 ZIP 需命名为 `Copyer-vX.Y.Z-Windows-x64.zip`，内部顶层为 `copyer-X.Y.Z/`，仅包含 `Copyer.exe` 和 `_internal/`。更新器检查 GitHub 上传资产的 SHA-256 digest；缺少资产或 digest 时可打开发布页。
- 更新仅在用户点击后联网，无后台自动检查。下载和解压在临时目录内完成；当前程序退出后，由独立 PowerShell 助手替换程序与运行库，新程序确认 Qt 窗口已启动后删除旧版本备份。替换或启动失败时回退；失败日志留在提示所示临时目录。
- `verify_update_installer.py` 在临时目录编译微型测试程序，实际运行同一更新助手，验证替换成功、启动失败回退、部分替换失败回退，以及中文/空格/单引号路径和用户额外文件保留。需要 Windows 自带 .NET Framework C# 编译器。
- 删除凭据只保存在本次任务内存中；重新扫描或更换目录后清空。确认弹窗列出文件。Windows 删除期间以文件句柄阻止两端写入或重命名，重新读取两端哈希后按同一源文件句柄删除。文件夹、失败项和未选文件不会被批量删除。
- 扫描只缓存当前会话中最多 20,000 个未变化文件的日期。按路径、设备/文件标识、大小、修改/创建时间及视频时区策略核验；失败读取不缓存，更换来源后清空。该缓存不参与复制或删除的内容校验。

## 精简包体

- 入口统一为 `Copyer.exe`，顶层只保留入口与 `_internal/`。
- `copyer.spec` 仅收集 Qt 窗口、ICO 插件、中文翻译与基础 Pillow 插件；不包含 JPEG 预览解码插件。Pillow 仅用于读取器不可用时的 JPEG 元数据回退。保留完整 ExifTool 解析代码，排除独立手册和地理数据库。
- 构建后 `tools/verify_package.py` 检查文件清单及原生 DLL 依赖，依赖不允许从开发环境补齐。
- `assets/ui-icons.json` 保存现有 12 个图标的矢量轮廓。仅重新导出图标时安装 `QtAwesome==1.4.1` 并运行 `tools/export_ui_icons.py`，导出完成后可卸载 QtAwesome 和 QtPy；应用和正式构建不依赖它。图标来源及许可见 `assets/licenses/`。
- 用户包不包含开发脚本、测试、截图或使用说明；必要的许可放在 `_internal/licenses/` 及读取器目录。
