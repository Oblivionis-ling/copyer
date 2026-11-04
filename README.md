# Copyer

将存储卡里的照片和视频，按拍摄日期导入电脑。Windows 10 / 11，免安装。

[下载便携版](https://github.com/Oblivionis-ling/copyer/releases/latest) · [更新记录](CHANGELOG.md)

1. 完整解压，打开 Copyer。
2. 选择来源和目标，扫描后按日期勾选需要导入的文件；需要时填写日期后的自定义名称。
3. 点击导入，校验完成后打开目标文件夹；需要腾出存储卡空间时，可删除本次已校验的源文件。

- 支持 25 种 RAW、JPEG / HEIF 照片和 MP4 / MOV / M4V 视频，包括佳能 CR3、DJI DNG 和 iPhone 素材。
- 优先读取拍摄日期；没有有效日期时使用修改时间。
- 导入使用 SHA-256 校验内容，同名文件不覆盖；默认保留来源，手动删除前再次校验两端文件。
- 可查看进度、取消导入、继续未完成项或重试失败项。
- 批量读取拍摄日期；同次运行中再次扫描会复用未变化文件的日期信息。
- 使用紧凑布局，不加载照片缩略图；设置直接在主窗口内切换，修改后自动保存。

设置中可检查 GitHub 新版本，确认后自动下载、校验并更新重启，也可查看支持格式、调整视频日期与显示偏好。请保留程序旁的 `_internal` 文件夹。

[格式与日期](docs/FORMATS.md) · [设计档案](https://github.com/Oblivionis-ling/copyer/tree/main/docs/design) · [开发文档](docs/DEVELOPMENT.md) · [第三方许可](THIRD_PARTY.md)

by Oblivionis-ling
