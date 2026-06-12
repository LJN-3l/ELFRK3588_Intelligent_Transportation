# 闯红灯抓拍原型脚本

这个脚本是桌面端命令行原型，目的是先把你的核心业务逻辑跑通：

- 读取本地视频
- 加载基础检测模型
- 可选加载头盔检测模型
- 框选红绿灯 ROI
- 圈出斑马线多边形区域
- 检测车辆目标
- 判断当前是红灯还是绿灯
- 对摩托车区域进行头盔二次识别
- 当车辆在红灯状态下进入斑马线时自动抓拍

## 运行方式

```bash
python outputs/red_light_violation_prototype.py --video path/to/video.mp4 --model yolo11n.pt --helmet-model your_helmet_model.pt --save-video
```

## 首次运行

第一次运行时需要手动完成区域标注：

- 框出红绿灯区域
- 点击斑马线多边形各个顶点
- 按 `Enter` 完成
- 程序会在视频旁边保存一个 `*_roi.json` 配置文件

## 常用参数示例

```bash
python outputs/red_light_violation_prototype.py ^
  --video your_video.mp4 ^
  --model yolo11n.pt ^
  --helmet-model your_helmet_model.pt ^
  --frame-skip 2 ^
  --stable-frames 5 ^
  --conf 0.25 ^
  --helmet-conf 0.30 ^
  --save-video
```

## 输出内容

- `captures/`：违章抓拍图片
- `violations.jsonl`：违章事件记录
- `annotated_output.mp4`：标注后视频，需开启 `--save-video`

## 给 K230 的迁移建议

这份脚本是 PC 端原型，不建议把完整的桌面 GUI、PyTorch 和 Ultralytics 直接搬到 K230。

最终迁移到 K230 时，建议保留“规则逻辑”，替换“运行方式”：

- 模型改成转换后的 `kmodel`
- ROI 坐标改为配置文件或固化参数
- 推理和抓拍逻辑改为板端实时运行
- 事件结果通过串口、网络或本地存储输出
