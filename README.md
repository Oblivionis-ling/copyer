# copyer

`copyer` 是一款面向 Windows 的读卡器照片与视频导入工具。它会扫描存储卡或指定目录中的媒体文件，按拍摄日期分组，并复制到目标目录。界面提供格式筛选、分组后缀、导入进度、执行日志和导入后源文件清理功能。

当前源码版本：`1.4.0`

> 仓库只保存源码、测试和构建配置，不提交 `build/`、`dist/`、可执行文件或发布压缩包。

## 功能概览

- 自动识别 Windows 可移动磁盘，也可手动选择任意源目录
- 递归扫描 RAW、JPEG 和常见相机视频文件
- JPEG 优先读取 EXIF 拍摄时间，其他文件或无有效 EXIF 时使用文件修改时间
- 按 `YYYY-MM-DD` 自动分组，并支持为每组添加自定义后缀
- 复制时保留文件元数据
- 目标目录存在同名文件时自动生成 `_1`、`_2` 等后缀，不覆盖原文件
- 显示逐文件导入进度与日志
- 记忆源目录、目标目录和格式选择
- 导入成功后，可在二次确认后删除本次已复制的源文件

## 支持的文件格式

| 类型 | 扩展名 |
| --- | --- |
| RAW | `.cr2`、`.cr3`、`.nef`、`.arw`、`.raf`、`.orf`、`.rw2`、`.dng` |
| JPEG | `.jpg`、`.jpeg` |
| 视频 | `.mp4`、`.mov`、`.m4v` |

扩展名匹配不区分大小写。RAW 和视频文件当前不读取拍摄元数据，使用文件修改日期分组。

## 使用方法

1. 打开程序，插入存储卡。
2. 点击“自动识别”，或点击“手动选择”指定源目录。
3. 选择目标目录和需要导入的文件格式。
4. 点击“扫描文件”，检查按日期生成的分组。
5. 如有需要，为日期分组填写后缀，例如 `2026-07-12-海边`。
6. 点击“开始导入”，等待进度显示“完成”。
7. 确认目标文件完整后，可选择删除本次已复制的源文件。

## 数据安全说明

- 导入操作使用复制，不会移动或覆盖源文件。
- 目标目录中遇到同名文件时会自动改名，已有文件保持不变。
- “删除存储卡已复制文件”只处理当前程序会话中最近一次成功导入所记录的源文件。
- 删除前会显示文件数量并要求再次确认；删除不可撤销，建议先检查目标目录或完成额外备份。

## 环境要求

- Windows 10 或 Windows 11
- Python 3.11（建议）
- 依赖见 `requirements.txt`

## 从源码运行

### 使用 venv

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe copyer.py
```

### 使用 Conda

```powershell
conda create -y -p .\.conda_env python=3.11 pip
conda run -p .\.conda_env python -m pip install -r requirements.txt
conda run -p .\.conda_env python copyer.py
```

## 运行测试

测试使用 Qt 的离屏平台，不会弹出应用窗口：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.conda_env\python.exe -m unittest discover -s tests -v
```

测试覆盖以下关键行为：

- 日期分组目录命名
- 同名文件防覆盖
- JPEG EXIF 日期读取与修改时间回退
- 多层目录扫描及格式筛选
- 文件复制、进度信号和复制结果
- `1.4.0` 版本的窗口尺寸、文案、默认选项、表头、样式及颜色基线

## 构建 Windows 发布包

安装依赖后执行：

```powershell
.\build_copyer.ps1
```

构建脚本优先使用项目内 `.conda_env\python.exe`；若该环境不存在，则使用 `PATH` 中的 Python。PyInstaller 会读取 `copyer-1.4.0.spec`，生成单目录发布包：

```text
dist/
└── copyer-1.4.0/
    ├── copyer-1.4.0.exe
    └── _internal/
```

`build/` 和 `dist/` 均为可重建产物，已被 Git 忽略。

## 项目结构

```text
copyer/
├── copyer.py              # 应用入口、界面与导入逻辑
├── tests/
│   └── test_copyer.py     # 核心功能和 UI 兼容性测试
├── tools/
│   └── generate_icon.py   # 应用图标生成工具
├── app_icon.ico           # Windows 应用图标
├── app_icon.png           # PNG 图标源
├── copyer-1.4.0.spec      # PyInstaller 构建配置
├── build_copyer.ps1       # Windows 构建脚本
└── requirements.txt       # 运行与构建依赖
```

## 常见问题

### 没有自动识别到存储卡

部分读卡器会被 Windows 识别为固定磁盘，而不是可移动磁盘。此时点击“手动选择”，直接选择对应盘符或照片目录即可。

### JPEG 没有按拍摄日期分组

程序会读取 EXIF 中的 `DateTimeOriginal`，其次读取 `DateTime`。如果照片没有这些字段、字段格式异常或文件无法解析，则使用文件修改日期。

### 导入后文件名出现 `_1`

目标目录已存在同名文件。程序为了避免覆盖，会保留原文件并为新文件追加递增编号。

### 构建脚本提示找不到 Python

请创建项目内 `.conda_env`，或确保已安装 Python 且 `python` 命令位于 `PATH` 中，然后重新运行构建脚本。
