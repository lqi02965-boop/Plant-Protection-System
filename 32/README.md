# STM32 主控端（F407VET6 核心板，标准库）

> 2026-09 改版：**泵/喷雾/继电器已全部移除**；诱虫灯改为 PWM 调光；上报从 PC 直连 TCP 改为**华为云 IoTDA MQTT**。

## 接线表

| 连接 | STM32 | 对端 | 备注 |
|------|-------|------|------|
| K230 串口 | PA2(TX2) / PA3(RX2) | K230 板载 TX/RX 排针 | TX↔RX 交叉，**必须共地**，115200 |
| ESP-01S | PB10(TX3) / PB11(RX3) | ESP-01S RX/TX | 交叉；ESP-01S 用**独立 3.3V** |
| DHT11 | PA1 | DHT11 DATA | 数据线 4.7K~10K 上拉 3.3V |
| 诱虫灯 | PA8 (TIM1_CH1) | N-MOS 模块信号脚（如 D4184） | PWM 调光，灯珠接 MOS 回路 |
| 按键 | PE4(KEY0) 灯开关 / PA0(WK_UP) 循环亮度档 | 板载按键 | |
| 调试 | PA9/PA10 | 板载 CH340 | 串口日志 115200 |
| 下载 | SWD | ST-Link | |

## Keil 工程搭建（同前）

标准库文件 `system_stm32f4xx.c`、`startup_stm32f40_41xxx.s`、`gpio/rcc/usart/misc`；
分组加 USER(main.c) + HARDWARE(delay/dht11/pwm_lamp/k230_uart/esp8266)；
宏定义 `STM32F40_41xxx, USE_STDPERIPH_DRIVER`；
`stm32f4xx_it.c` 里接：

```c
void USART2_IRQHandler(void) { K230_Uart_IRQHandler(); }
void USART3_IRQHandler(void) { ESP8266_IRQHandler(); }
```

（SysTick_Handler 已在 main.c 定义，it.c 原有空实现删掉。）

## 必须填的配置（USER/config.h + main.c 顶部）

| 配置 | 来源 |
|------|------|
| `WIFI_SSID / WIFI_PASS` | 现场 WiFi |
| `IOT_SERVER` | 华为云 IoTDA 控制台"总览→接入信息"，如 `iot-mqtts.cn-north-4.myhuaweicloud.com` |
| `IOT_DEVICE_ID / IOT_DEVICE_SECRET` | IoTDA 建设备后得到 |
| `IOT_SERVICE_ID` | 产品模型服务 ID，须与小程序 config.js 一致（默认 PestMonitor） |

**ESP-01S 的 AT 固件必须 ≥ 2.0**（AT+MQTT* 指令），用 `AT+GMR` 确认。

## 华为云 MQTT 认证（ESP8266 算不了 HMAC 的原因）

- `clientId = {device_id}_0_0`，`username = {device_id}`，`password = 设备密钥`
- 华为规则：时间戳位为 0 时 password 直接填密钥，因此无需 HMAC-SHA256

## 数据协议

| 方向 | 主题 | 内容 |
|------|------|------|
| 设备→云 | `$oc/devices/{id}/sys/properties/report` | `{"services":[{"service_id":"PestMonitor","properties":{"temp":25.6,"humi":60,"pests":3,"lamp_on":1,"brightness":50}}]}` |
| 云→设备 | `$oc/devices/{id}/sys/commands/#` | `{"paras":{"lamp_on":1,"brightness":80}}`，设备回 response 主题 |

K230→STM32 仍是 `$n#` 串口帧。

## 面试点

- **MQTT 物模型**：属性上报/命令下发两套 `$oc` 主题；AT 指令里 JSON 引号转义
- **PWM 调光**：TIM1 1kHz，占空比 0~100%，MOS 管做功率级——继电器只能开关做不了亮度
- **离线降级**：WiFi/MQTT 失败只影响上云，本地检测和按键调灯照常

## 待改进

- MQTT 上报仍用阻塞 SendCmd，可改环形缓冲异步化
- 命令 JSON 解析用 strstr 简化实现，字段复杂时建议上轻量 cJSON
