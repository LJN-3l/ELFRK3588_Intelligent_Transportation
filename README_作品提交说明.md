# 智能交通双端执法辅助系统 - 作品重点代码

本目录整理了作品提交所需的重点代码，按运行端分为 K230 摄像头端、RK3588 网页端、Windows 客户端和部署脚本。

## 一、系统功能概述

本作品实现 K230 摄像头采集、RK3588 网页实时展示与 YOLO 辅助检测、Windows 客户端录像批处理、人工审核、报告生成和车流量统计。

核心功能包括：

- K230 摄像头采集画面，通过 UART2 + CH340 向 RK3588 推送 JPEG 帧。
- RK3588 接收串口帧并提供 MJPEG 视频流。
- RK3588 网页端显示实时画面、AI 叠加画面、人工审核队列、ROI 标定、报告生成。
- Windows 客户端支持导入录像、框选红绿灯和斑马线 ROI、调用基础车辆模型和头盔模型。
- 支持闯红灯抓拍、未戴头盔抓拍、人工确认/驳回/去重。
- 支持快速结构化报告和 AI 润色报告两种模式。
- 支持车流量统计，并按车辆数量显示畅通、缓行、拥堵状态。

## 二、目录说明

```text
01_K230端摄像头串口推流/
  k230_uart_stream_fast.py

02_RK3588网页端与实时AI/
  web_dashboard_v4.py
  mjpeg_server_fast.py

03_Windows客户端EXE源码/
  red_light_violation_gui.py
  red_light_violation_prototype.py
  launch_red_light_violation.py
  build_gui_exe.bat
  build_launcher_exe.bat
  RedLightViolationAssistant.exe

04_部署脚本/
  start_all_cat_eof.sh
  install_mjpeg_server_fast_cat_eof.sh
  setup_yolo_sd_target_cat_eof.sh
  repair_ultralytics_sd_no_torchvision_cat_eof.sh
  fix_rk_yolo_start_env_cat_eof.sh
  add_report_fast_ai_modes_cat_eof.sh
  add_traffic_flow_web_cat_eof.sh
  fix_review_queue_hotfix_cat_eof.sh
  fix_roi_editor_hotfix_cat_eof.sh

05_模型文件/
  yolo11n.pt
  yolov11n_hemlet.pt
  best_260424_0028.pt
  示例视频_roi.json

06_说明文档/
  K230_RK3588_接入说明.md
  RK3588_双端互通使用说明.md
  red_light_violation_gui_README.md
  red_light_violation_prototype_README.md
```

## 三、RK3588 端启动方式

RK3588 上最终一键启动脚本为：

```sh
sh /root/start_all.sh
```

启动后访问：

```text
http://192.168.137.82:5000
```

主要服务链路：

```text
K230 摄像头
-> UART2 串口
-> CH340
-> RK3588 /dev/ttyUSB0
-> /root/mjpeg_server.py 或 /root/mjpeg_server_fast.py
-> http://0.0.0.0:5001/video
-> /root/web_dashboard_v4.py
-> 浏览器 http://192.168.137.82:5000
```

## 四、模型路径

RK3588 推荐模型路径：

```text
/root/models/yolo11n.pt
/root/models/yolov11n_hemlet.pt
```

如果使用 SD 卡扩展 Python 库：

```text
/media/elf/E76C-92AC1/pylibs
```

## 五、Windows 客户端使用方式

可直接运行：

```text
03_Windows客户端EXE源码/RedLightViolationAssistant.exe
```

或使用源码启动：

```bat
python red_light_violation_gui.py
```

重新打包 EXE：

```bat
build_gui_exe.bat
```

## 六、提交说明

本压缩包重点保存代码和关键运行脚本。视频测试素材、缓存文件、构建中间目录和日志文件未放入，以减少体积并突出作品核心实现。
