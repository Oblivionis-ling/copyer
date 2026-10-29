# 开发与构建


开发环境：Windows 10/11、Python 3.11、PySide6。建议使用项目内 Conda 环境：

```powershell
conda create -y -p .\.conda_env python=3.11 pip
$env:PYTHONNOUSERSITE = '1'
.\.conda_env\python.exe -m pip install -r requirements.txt
.\.conda_env\python.exe tools\fetch_exiftool.py
.\.conda_env\python.exe copyer.py
```

测试及打包：

```powershell
$env:PYTHONNOUSERSITE = '1'
.\.conda_env\python.exe -m unittest discover -s tests -v
.\build_copyer.ps1
```

构建脚本使用 `.conda_env\python.exe` 并隔离 DLL 搜索路径。`copyer.spec` 从 `copyer_version.py` 读取版本，生成 `dist/copyer-1.5.2/`。首次构建会下载固定版本的 ExifTool，并校验官方 SHA-256；也可以用 `tools/fetch_exiftool.py --archive 下载好的ZIP` 离线准备。源码仓库不提交环境、第三方二进制、构建输出和便携压缩包。

## 验证与项目结构

- `copyer.py`：应用入口。
- `copyer_ui.py`：原生 Qt 界面和任务状态。
- `copyer_materials.py`：中性方格、控件折射和透明窗框绘制。
- `copyer_core.py`：扫描、计划、复制和校验，不依赖界面。
- `copyer_metadata.py`：RAW / 照片 / 视频日期选择、时区策略与后台读取进程。
- `tests/`：文件异常、取消、重试、线程生命周期和界面交互测试。
- `tools/capture_ui.py` / `tools/capture_states.py`：隔离测试媒体及 Qt 界面截图，不写入正式用户设置。
- [第三方组件与来源](THIRD_PARTY.md)。
- [更新记录](CHANGELOG.md)。

v1.5.2 的 64 项测试中，61 项通过，3 项真实符号链接测试因 Windows 权限不足跳过。包含 10 种 RAW 的真实元数据样本，以及 HEIF、Apple/DJI 字段、跨日时区、超时与取消测试。测试样本保留元数据，并非完整可解码的原片；支持列表不代表每款相机都做过实机验证。读卡器热拔插和掉电恢复尚未验证。

## 精简包体

- 入口统一为 `Copyer.exe`，顶层只保留入口与 `_internal/`。
- `copyer.spec` 仅收集 Qt 窗口、JPEG / ICO 插件、中文翻译与基础 Pillow 插件；保留完整 ExifTool 解析代码，排除独立手册和地理数据库。
- 构建后 `tools/verify_package.py` 检查文件清单及原生 DLL 依赖，依赖不允许从开发环境补齐。
- `assets/ui-icons.json` 保存现有 12 个图标的矢量轮廓。仅重新导出图标时需要 QtAwesome 1.4.1：运行 `tools/export_ui_icons.py`；应用和正式构建不依赖它。图标来源及许可见 `assets/licenses/`。
- 用户包不包含开发脚本、测试、截图或使用说明；必要的许可放在 `_internal/licenses/` 及读取器目录。
