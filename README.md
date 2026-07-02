# DOGZILLA-LITE Vision Reaction

独立视觉反应小项目：检测画面里的红色目标，然后让机器狗做一个简单反应。

当前版本先做两个可观察动作：

- `forward`: 看到红色目标后向前走一小段，然后自动停止。
- `crouch`: 看到红色目标后尝试下蹲或降低机身高度。这个动作依赖机器狗本机 DOGZILLA 库是否暴露姿态接口，建议先 dry-run，再上机器狗测试。
- `grab`: 看到红色目标后执行官方机械臂抓取序列，伸出机械臂并尝试夹取。

默认是 dry-run，只打印将要执行的动作，不会真的控制机器狗。只有加 `--live` 才会调用机器狗接口。

参考资料：

- Yahboom DOGZILLA-Lite 学习页：https://www.yahboom.com/study/DOGZILLA-Lite
- Yahboom DOGZILLA-Lite 官方资料仓库：https://github.com/YahboomTechnology/DOGZILLA-Lite

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

dry-run 检测并模拟机械臂抓取：

```bash
python3 -m dogzilla_vision_reaction.cli image \
  --image demo/red_target.png \
  --action grab
```

官网基础功能 dry-run 验收：

```bash
python3 -m dogzilla_vision_reaction.cli hardware motion --speed 7 --seconds 0.1 --include-lateral
python3 -m dogzilla_vision_reaction.cli hardware audio --frequency 660 --seconds 0.1
python3 -m dogzilla_vision_reaction.cli hardware stream --robot-ip 192.168.137.252 --port 8000
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

测试红球触发机械臂抓取，先 dry-run：

```bash
python3 -m dogzilla_vision_reaction.cli camera \
  --action grab \
  --capture-output demo/red_ball_frame.jpg \
  --annotated demo/red_ball_annotated.jpg
```

确认输出里 `reaction.action` 是 `grab` 后，再真实执行：

```bash
python3 -m dogzilla_vision_reaction.cli camera \
  --action grab \
  --live \
  --capture-output demo/red_ball_frame.jpg \
  --annotated demo/red_ball_annotated.jpg
```

真实抓取默认会先做靠近/对齐，再执行机械臂抓取：

- 红球偏左或偏右：先小步横移对齐。
- 红球面积太小：先小步前进。
- 红球过近：先小步后退。
- 红球居中且足够近：执行 `grab` 机械臂动作。

可以调这些参数：

```bash
python3 -m dogzilla_vision_reaction.cli camera \
  --action grab \
  --live \
  --grab-max-steps 12 \
  --grab-ready-area-ratio 0.025 \
  --grab-center-tolerance 45 \
  --grab-approach-speed 6 \
  --grab-approach-seconds 0.3
```

### 2.1 基础硬件验收

这些命令对应官网里的基础能力：运动控制、播放声音、摄像头视频/图传。建议先 dry-run，再 live。

运动测试，先前进再后退：

```bash
python3 -m dogzilla_vision_reaction.cli hardware motion \
  --live \
  --speed 8 \
  --seconds 0.4
```

运动测试，增加左右平移：

```bash
python3 -m dogzilla_vision_reaction.cli hardware motion \
  --live \
  --speed 8 \
  --seconds 0.4 \
  --include-lateral
```

发出一个短音：

```bash
python3 -m dogzilla_vision_reaction.cli hardware audio \
  --live \
  --frequency 880 \
  --seconds 0.35
```

如果机器狗上没有默认播放器，可以指定 `aplay`：

```bash
python3 -m dogzilla_vision_reaction.cli hardware audio \
  --live \
  --player-command aplay \
  --frequency 880 \
  --seconds 0.35
```

把摄像头视频直播到电脑浏览器：

```bash
python3 -m dogzilla_vision_reaction.cli hardware stream \
  --live \
  --host 0.0.0.0 \
  --port 8000 \
  --robot-ip 192.168.137.252
```

然后在电脑浏览器打开输出里的 `computer_url`，例如：

```text
http://192.168.137.252:8000
```

如果你还没确认摄像头环境，可以先在电脑上跑测试图案流：

```bash
python3 -m dogzilla_vision_reaction.cli hardware stream \
  --live \
  --test-pattern \
  --host 127.0.0.1 \
  --port 8000
```

## 3. 参数说明

- `--min-area-ratio`: 红色区域至少占画面的比例，默认 `0.003`。误检多就调大。
- `--confidence-threshold`: 触发动作的最低置信度，默认 `0.30`。机器狗误动就调高。
- `--min-red`: 红色通道最低值，默认 `100`。环境偏暗时可调低。
- `--dominance-delta`: 红色比绿色/蓝色至少高多少，默认 `25`。误检多就调高。
- `--confidence-full-area-ratio`: 目标占画面多少时视为满置信度，默认 `0.02`。
- `--grab-approach` / `--no-grab-approach`: 开启或关闭抓取前的自动靠近/对齐。默认开启。
- `--grab-center-tolerance`: 红球中心允许偏离画面中心多少像素，默认 `45`。
- `--grab-ready-area-ratio`: 抓取前红球需要占画面的最小比例，默认 `0.025`。抓不到通常调大一点，让狗再靠近。
- `--grab-too-close-area-ratio`: 红球占画面比例超过这个值时先后退，默认 `0.09`。
- `--grab-max-steps`: 抓取前最多靠近/对齐几步，默认 `12`。
- `--action`: 触发动作，支持 `forward`、`crouch` 或 `grab`。
- `--live`: 真正控制机器狗。没有这个参数只做 dry-run。
- `--forward-speed`: 向前速度，默认 `8`，建议第一次别调太大。
- `--seconds`: 动作持续时间，默认 `0.5` 秒。
- `hardware motion --speed`: 基础运动测试速度，默认 `8`。
- `hardware stream --robot-ip`: 机器狗 IP，只用于生成电脑浏览器打开的 URL。

## 4. 安全建议

第一次 live 测试时把机器狗放在空旷地面，速度和时间都用小值。发现不对直接按 `Ctrl+C`，程序会尽量发送停止命令。
