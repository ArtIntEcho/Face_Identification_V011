# Face Access

Windows PC 上的人脸认证门禁原型。当前版本已接通 SCRFD 检测、ArcFace 512 维模板、MediaPipe 主动活体、MiniFASNet 双模型被动活体、1:N 检索、审计日志和本地 Web 工作台。

## 运行

```powershell
.venv/Scripts/python.exe -m pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv/Scripts/python.exe -m uvicorn face_access.main:app --host 127.0.0.1 --port 8000
```

使用 Edge 打开 `http://127.0.0.1:8000`。首次使用时初始化管理员，然后新增人员。在“授权人员”页点击“注册人脸”，推荐选择“现场采集”，按正面、左右转头、抬头和低头提示拍摄 3–5 张照片；也可切换到“上传照片”作为备选。返回认证页启动摄像头，在 15 秒内按画面上方提示完成眨眼和指定方向转头；超时后可直接重试，无需关闭摄像头。

## 测试

```powershell
.venv/Scripts/python.exe -m pytest -q
```

## 模型产物

- `scrfd_500m_bnkps.onnx`：640×640 人脸检测和五点关键点；
- `mbf.onnx`：112×112 ArcFace MobileFaceNet，输出 512 维特征；
- 两份 `MiniFASNet` ONNX：80×80、2.7/4.0 倍扩框融合，真实脸类别索引为 1；
- `tools/export_minifasnet.py`：从 MiniVision 官方 Apache-2.0 仓库下载权重并复现导出，需安装 `.[export]`。

## 当前边界

- PAD 阈值 `0.80` 和相似度阈值 `0.75` 是当前配置值，尚未用现场人员集和打印/屏幕/视频攻击集标定，不能据此宣称达到最终 FAR 或攻击防御指标。
- InsightFace 预训练权重的授权必须在商业部署前完成法务审查。
- 当前 Windows PC 使用 ONNX Runtime；Hailo-8 的 HEF 编译、INT8 精度和端到端性能必须在外部 Hailo 平台实测。
