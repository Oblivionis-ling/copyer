# copyer

读卡器照片 / 视频导入工具。

当前上传的是最新版源码快照，不包含 `build/`、`dist/`、exe、pkg、rar 等构建产物。

## 功能

- 自动识别 Windows 可移动磁盘
- 扫描 RAW、JPEG、MP4/MOV/M4V 文件
- 按拍摄日期或文件修改日期分组
- 支持为每个日期分组添加自定义后缀
- 将文件复制到目标目录
- 支持打开目标目录
- 支持在确认后删除已复制的源文件
- 保存常用路径和格式选择

## 源码结构

- `test.py`：主程序入口
- `app_icon.ico` / `app_icon.png`：应用图标
- `copyer-1.3.3.spec`：最新版 PyInstaller 构建配置
- `build_copyer.ps1`：Windows 构建脚本
- `tools/generate_icon.py`：图标生成辅助脚本

## 运行

```powershell
pip install -r requirements.txt
python test.py
```

## 构建

```powershell
pip install -r requirements.txt
.\\build_copyer.ps1
```

构建结果会生成到 `dist/`，该目录不会提交到 Git。
