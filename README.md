# DOGZILLA-LITE Vision Reaction

独立视觉反应小项目：检测画面里的红色目标，然后让机器狗做一个简单反应。

当前版本先做两个可观察动作：

- `forward`: 看到红色目标后向前走一小段，然后自动停止。
- `crouch`: 看到红色目标后尝试下蹲或降低机身高度。这个动作依赖机器狗本机 DOGZILLA 库是否暴露姿态接口，建议先 dry-run，再上机器狗测试。

默认是 dry-run，只打印将要执行的动作，不会真的控制机器狗。只有加 `--live` 才会调用机器狗接口。

## 1. 本机验证

安装依赖：

```bash
pip3 install -r requirements.txt
```

运行测试：

```bash
python3 -m unittest discover -s tests
```

生成一张红色目标测试图：

```bash
python3 scripts/make_demo_image.py --output demo/red_target.png
```

dry-run 检测并模拟向前走：

```bash
python3 -m dogzilla_vision_reaction.cli image \
  --image demo/red_target.png \
  --action forward \
  --annotated demo/annotated.png \
  --json demo/result.json
```

dry-run 检测并模拟下蹲：

```bash
python3 -m dogzilla_vision_reaction.cli image \
  --image demo/red_target.png \
  --action crouch
```

## 2. 机器狗上测试

先把项目放到机器狗上，进入项目目录后安装依赖：

```bash
pip3 install -r requirements.txt
```

摄像头识别红色目标，但先 dry-run：

```bash
python3 -m dogzilla_vision_reaction.cli camera \
  --action forward \
  --capture-output demo/camera_frame.jpg
```

确认识别正常后再 live：

```bash
python3 -m dogzilla_vision_reaction.cli camera \
  --action forward \
  --live \
  --forward-speed 8 \
  --seconds 0.4
```

测试下蹲：

```bash
python3 -m dogzilla_vision_reaction.cli camera \
  --action crouch \
  --live \
  --seconds 0.4
```

如果下蹲报接口不支持，先保留 `forward` 动作做展示，之后再根据机器狗本机示例代码里的姿态函数补准确接口。

## 3. 参数说明

- `--min-area-ratio`: 红色区域至少占画面的比例，默认 `0.01`。误检多就调大。
- `--confidence-threshold`: 触发动作的最低置信度，默认 `0.50`。机器狗误动就调高。
- `--action`: 触发动作，支持 `forward` 或 `crouch`。
- `--live`: 真正控制机器狗。没有这个参数只做 dry-run。
- `--forward-speed`: 向前速度，默认 `8`，建议第一次别调太大。
- `--seconds`: 动作持续时间，默认 `0.5` 秒。

## 4. 安全建议

第一次 live 测试时把机器狗放在空旷地面，速度和时间都用小值。发现不对直接按 `Ctrl+C`，程序会尽量发送停止命令。
