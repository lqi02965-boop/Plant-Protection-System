# 农田虫害智能监测系统 — 任务清单（v2 小程序+华为云版）

> 业务闭环：害虫飞向诱虫灯 → K230 拍照检测计数 → 虫数/温湿度经 STM32 → 华为云 IoTDA → **手机小程序**查看；小程序可调诱虫灯亮度。
> ~~喷雾泵~~ 已按需求取消（泵、继电器、喷雾状态机代码已删）。

## 工程目录

> 📚 **完整技术文档已归档到 Obsidian 库**：`D:\knowledge\实战项目-植保系统\`
> 共 10 篇笔记（项目总览 / 硬件清单与接线 / STM32主控端固件 / K230视觉检测端 / 华为云IoTDA配置 /
> 微信小程序端 / 部署与烧录流程 / 故障排查与踩坑记录 / 功能扩展指南 / 协议与接口速查）。
> **后续加功能前先看《08-功能扩展指南》。**

```
230/  K230 视觉端：YOLOv8检测计数 + MJPG推流 + /snapshot快照 + LCD显示 + UART上报   ✅ 已完成
32/   STM32 主控端（F407VET6 标准库）：DHT11 + PWM调光灯 + ESP8266 MQTT连华为云      ✅ 已联调
mp/   微信小程序：温湿度/虫数/灯亮度显示 + 开关/亮度滑条控制                        ✅ 已跑通
py/   （已废弃为主方案，仅留作 K230 推流调试工具）
```

## 架构 v2

```
K230 --UART "$n#"--> STM32 --MQTT--> 华为云 IoTDA <--HTTPS API-- 微信小程序
 |                     |  ▲
 |                     |  └-- 命令下发(lamp_on/brightness) -> TIM1 PWM -> MOS -> 灯珠
 +-- MJPG/snapshot --> 浏览器/小程序image
 +-- LCD(ST7701) ----> 现场屏幕直显检测结果
```

## 一、硬件与器件

| 器件 | 型号 | 状态 |
|------|------|------|
| 视觉板 | 亚博 K230 豪华板 + 3.1寸 MIPI 屏(ST7701) | ✅ 已跑通检测+屏显 |
| 主控 | STM32F407VET6 核心板 | ✅ 工程已建、编译通过 |
| WiFi | ESP-01S（**AT 固件须 ≥2.0**，`AT+GMR` 待查） | ⬜ |
| 温湿度 | DHT11 | ✅ |
| 诱虫灯 | 紫光 LED 灯珠 + **N-MOS 调光模块（型号待确认，推荐 D4184）** | ⬜ 报型号 |
| 供电 | 12V 适配器 + LM2596 5V + 独立 3.3V 给 ESP-01S | ✅ |
| ~~泵/继电器/喷雾~~ | —— | ❌ 已取消 |

## 二、STM32 端

- [x] 删除泵/继电器/喷雾状态机
- [x] PWM 调光（pwm_lamp.c，TIM1_CH1 PA8，1kHz 0~100%）
- [x] ESP8266 改华为云 MQTT（esp8266.c：USERCFG/CONN/SUB/PUB + 下行命令缓存）
- [x] main.c：属性上报 JSON + 云命令解析（lamp_on/brightness）+ 按键本地控制
- [x] 填 config.h：IoT 地址/设备ID/密钥/服务ID（已用旧版可用参数）
- [x] **Keil 工程建好并编译通过**（`32/PestMonitor.uvprojx`，AC5，0 error 0 warning）
- [ ] 填 main.c 顶部 WiFi（`WIFI_SSID/WIFI_PASS`）
- [x] ST-Link 烧录 + 单测（PWM 调灯 / 按键 / USART1 日志）
- [x] ESP-01S 联网 + MQTT 连云（控制台显示设备 **ONLINE**）
- [x] 华为云控制台验证上行属性（影子 `temp/humi/pests/lamp_on/brightness` 持续刷新）
- [x] **云端命令下发打通**（小程序/控制台改亮度 → 设备收到 → PWM 变化 → 回执 result_code=0）
- [ ] DHT11 换新（当前 `err=3` 无应答，模块故障；`idle=1` 说明接线时序已对）
- [ ] K230 → STM32 接线（IO11→PA3、IO12→PA2、共地）→ 串口出 `pest=n`

### STM32 云命令收不到 —— 根因与修法（实测定位，面试亮点）

| 现象 | 真实原因 | 修法 |
|------|----------|------|
| 云侧一直报 `IOTDA.014111 Command request timed out`，串口**一个 `+IPD` 都没有** | 旧版把 AT 回显和下行 MQTT 报文塞进同一个 `recv_buf`，主循环用"连续两圈内容不变=收完了"当判据；但主循环是**微秒级**空转、串口一字节要 **87µs** → 缓冲里刚进 1 字节就被判定"收完"并 `recv_clear()`，整条 `+IPD` 被逐字节拆碎丢光（串口实测刷出 `RX(len=1): 76 / 62 / 6D …`） | 在 **USART3 中断里用状态机**把 `+IPD,<len>:<data>` 的 data 抽到**独立缓冲 `ipd_buf`**，与主循环节奏彻底解耦；解析判据改为**距最后一字节空闲 >120ms** |
| `[mqtt-tx] no '>'` + ESP 回 `busy s...`，30s 一次误判"链路已死"整链重连 | `net_mqtt_send` 发出数据后用 `strstr(recv_buf,"OK")` 判成功，而缓冲里**残留着上一条 `AT+CIPSEND` 的 "OK"** → 提前返回"成功"，ESP 还在发送中就被下一条 CIPSEND 撞车 | 发出数据后**先 `recv_clear()`**，只认之后的 **`SEND OK`**；`busy` 时退避重试 |
| 拿到 `request_id` 拼不对回执主题 | topic 长度前缀里含 `0x00`，用字符串搜索会被截断；QoS>0 时主题后还有 2 字节报文ID | 按 **MQTT PUBLISH 结构**解析（变长剩余长度 → 主题长度 → 主题区 → 载荷区），只在载荷区做 `0x00`→`.` 消毒 |
| 小程序拖滑条"没提示、2 秒后自己弹回 60%" | 下发接口等设备回执最长 25s，期间 5s 轮询用云端旧值覆盖了滑条；且滑条回调**只有 `.catch()` 没有成功 toast**，而 `HTTP 200 + error_code` 被当成成功 | 小程序：`error_code` 显式判错；下发后 `cmdHoldUntil` 8s 内不被轮询覆盖；补成功/失败 toast |


## 三、K230 端 ✅ 已完成

- [x] 训练 yolov8s（自采 pest_dataset，nc=1，imgsz=640，50 epochs）→ best.onnx
- [x] 转换 best.kmodel（**nncase 2.11 + nncase-kpu**，见下方关键参数）
- [x] main.py：AI2D letterbox 预处理 + 自写 YOLOv8 无锚框解码 + NMS
- [x] 双通道取图：CHN1=RGB565(画框/推流/屏显)、CHN2=平面RGB888(喂 AI)
- [x] MJPG 推流 + `/snapshot` 单帧 + UART `$n#` 上报
- [x] LCD 屏显（3.1寸 ST7701，`osd_num=2`，检测结果显到 OSD1 层）
- [x] 上板实测：LCD 出画面 + 画框 + 虫数，识别正常
- [x] 诊断工具：`ai_dump.py`(导出模型输入+推送)、`_debug_onnx.py`、`_debug_kmodel.py`(PC 端模拟器验证)

### K230 部署关键参数（踩坑记录，面试可用）

| 项目 | 正确值 | 踩过的坑 |
|------|--------|----------|
| kmodel 目录 | `/sdcard/kmodel/best.kmodel`（12,475,904 字节） | — |
| AI 库 | 板子自带 `/sdcard/libs/`（AIBase/AI2D/PipeLine） | 不用自己传，但路径不是 `/sdcard/app/libs` |
| **nncase 预处理** | `input_range=[0,255]`, `mean=0`, **`std=[255,255,255]`** | 写成 `std=[1,1,1]` → 输入放大 255 倍 → 分数饱和、满屏乱框 |
| 目标插件 | 必须装 `nncase-kpu`（不在 PyPI，去 GitHub Release 下 whl） | 不装报 `KeyNotFoundException: 'k230'` |
| AI 通道格式 | `PIXEL_FORMAT_RGB_888_PLANAR`（平面=CHW） | 用普通 RGB888 → 喂错数据 |
| 推流/画框通道 | `PIXEL_FORMAT_RGB_565` | JPEG 编码器不支持 RGB888，报 `current format not support save` |
| 喂 AI 的数据 | `frame.to_numpy_ref()` 后再传 | 直接传图像对象会错（AIBase 内部是 `nn.from_python`） |
| 屏显 | `Display.init(..., osd_num=2)` + 显示到 `LAYER_OSD1` | 不给 `osd_num` → OSD 层不存在，`show_image` 静默失效 |
| 固件缺的 API | `os.path.*`、`sys.print_exception`、`image.to_bytes()` 都没有 | 分别用 `os.stat()`、自己打印、`bytearray()` 替代 |

## 四、微信小程序端（mp/）

- [x] 页面：温湿度/虫数卡片 + 灯开关 + 亮度滑条 + 在线状态
- [x] utils/huawei.js：IAM token → IoTDA 查属性/下发命令
- [x] 5s 轮询刷新、下发防抖
- [x] `error_code` 判错 + 下发期间不被轮询覆盖 + 成功/失败 toast
- [x] **填 mp/config.js**（区域 cn-north-4 / 应用接入域名 / projectId / IAM / 设备ID / 服务ID）
- [x] 开发者工具导入 + "不校验合法域名" 联调（影子查询 200，下发命令设备生效）
- [ ] 界面最终演示（等 DHT11 换新 + K230 接线后数据非 0）

## 五、需要用户提供的数据

| 数据 | 用途 | 从哪拿 |
|------|------|--------|
| ~~IoTDA 接入地址~~ | 32/config.h | ✅ 已填（cn-north-4） |
| ~~设备ID + 设备密钥~~ | 设备认证 | ✅ 已填（6a83ca9...\_shebei） |
| IAM 项目ID (projectId) | mp/config.js | 我的凭证→项目列表 |
| IAM 用户名/密码/域名 | mp/config.js | 统一身份认证服务 |
| MOS 调光模块型号 | 硬件 | 你买/已有，报型号 |
| WiFi SSID/密码 | 32/main.c + 230/main.py | 现场 2.4G 网络 |

## 六、联调顺序（当前进度标 ✅）

1. ✅ **K230 单测完成**：检测 + 计数 + LCD 显示 + 串口帧输出
2. ⬅ **STM32 单测**：DHT11 读数、PWM 调灯、按键、USB 串口日志
3. ESP-01S：AT+GMR 确认 ≥2.0 → WiFi → MQTT 连上（控制台看设备在线）
4. 云验证：控制台"设备影子"看到 temp/humi，再补 pests
5. 命令下行：控制台"命令下发"测试 set_lamp → 灯亮度变化
6. **K230 → STM32 接线**：IO11→PA3、IO12→PA2、**共地** → 串口日志出 `pest=n`
7. 小程序：导入 mp/ 填 config.js → 数据显示 + 滑条调光

## 七、面试亮点（对应代码）

| 亮点 | 代码 |
|------|------|
| 模型全流程部署（自训 → ONNX → kmodel → 板端推理） | `230/main.py` + `yolo/convert_kmodel.py` |
| 边缘计算：检测/计数/调灯本地闭环，断网不影响 | `230/main.py` + `32/USER/main.c` |
| YOLOv8 无锚框解码 + NMS 手写实现 | `230/main.py` → `PestDetApp.postprocess()` |
| AI2D 硬件预处理（letterbox）+ AI2D/KPU 零拷贝 | `230/main.py` → `config_preprocess()` |
| 物联网物模型：属性上报/命令下发 | `32/HARDWARE/esp8266.c` + `mp/utils/huawei.js` |
| MQTT 设备侧认证（免 HMAC 方案） | `32/USER/config.h` 注释 |
| PWM 调光 + MOS 功率级 | `32/HARDWARE/pwm_lamp.c` |
| 小程序调云 API（IAM token 缓存/命令防抖） | `mp/utils/huawei.js` + `pages/index/index.js` |
