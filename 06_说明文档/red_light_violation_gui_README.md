# 闯红灯抓拍助手 GUI 版

## 功能概览

这是一套面向你当前项目的桌面原型工具，默认中文界面，并支持中英切换。

它可以完成这些事情：

- 选择本地视频文件
- 选择基础 YOLO 检测模型
- 选择头盔检测模型
- 第一次运行时框选红绿灯区域和斑马线区域
- 自动识别车辆在红灯状态下进入斑马线的行为
- 对摩托车区域做头盔二次识别
- 自动保存抓拍图片、事件日志和标注后视频

## 启动方式

```bash
python outputs/red_light_violation_gui.py
```

## 使用步骤

1. 打开程序
2. 在“视频文件”里选择待检测视频
3. 在“基础模型”里选择 `.pt` 模型，默认可先试 `yolo11n.pt`
4. 在“头盔模型”里选择你的头盔识别模型
5. 选择输出目录
6. 点击“开始检测”

如果当前视频还没有 ROI 配置，程序会弹出 OpenCV 窗口让你：

1. 框选红绿灯区域
2. 用多边形圈出斑马线区域

完成后会自动生成一个 `.json` 配置文件，下次可直接复用。

## 滚动页面

当窗口高度较小时，可以直接使用鼠标滚轮上下滚动整个页面，底部的控制区和日志区都能看到。

## 预览窗口大小

运行检测时，OpenCV 预览窗口会自动按固定比例缩放到适合屏幕的大小，大分辨率视频不会再直接满屏撑开。

## 主要按钮

- `开始检测`：启动检测任务
- `停止检测`：请求安全停止
- `打开输出目录`：直接在资源管理器中打开结果目录

## 输出结果

输出目录内通常会包含：

- `captures/`：违章抓拍图
- `violations.jsonl`：违章事件记录
- `annotated_output.mp4`：标注后视频

## 依赖安装

```bash
pip install opencv-python ultralytics numpy
```

## 打包 exe

已经提供一键打包脚本：

- [build_gui_exe.bat](C:/Users/Username/Documents/Codex/2026-06-04/from-machine-import-uart-fpioa-import/outputs/build_gui_exe.bat)
- [build_launcher_exe.bat](C:/Users/Username/Documents/Codex/2026-06-04/from-machine-import-uart-fpioa-import/outputs/build_launcher_exe.bat)

双击它，或者在命令行里运行：

```bash
outputs\build_gui_exe.bat
```

默认会自动安装 `PyInstaller`，然后生成：

```text
outputs\dist\SmartTrafficAssistant\SmartTrafficAssistant.exe
```

如果你当前机器上使用 `PyInstaller + torch` 的完整冻结版不稳定，建议直接使用这个更稳的启动器 exe：

- [SmartTrafficAssistant.exe](C:/Users/Username/Documents/Codex/2026-06-04/from-machine-import-uart-fpioa-import/outputs/SmartTrafficAssistant.exe)

它仍然是双击启动的 `exe`，但会调用当前机器上已经正常工作的 Python 环境来运行 GUI，因此更适合你现在这套 `ultralytics + torch` 组合。

## 后续建议

当这套 GUI 工作流稳定后，你可以继续做两步：

- 把这里已经验证过的规则逻辑迁移到 K230 端运行
- 再增加历史事件回看、批量导出报告等成品化功能
