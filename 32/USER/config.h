#ifndef _CONFIG_H
#define _CONFIG_H
/* ============================================================
 * 项目硬件配置（所有引脚/参数集中在这，改硬件只改这里）
 * 主控: STM32F407VET6 核心板, 标准库, Keil5
 * 业务: K230检测虫数 + DHT11温湿度 + PWM调光诱虫灯 + 华为云IoT上报
 *       （泵已取消，无继电器、无喷雾）
 * ============================================================ */

/* ---------------- 诱虫灯: PWM 调光 (需 N-MOS 驱动模块, 如 D4184) ----------------
 * PA8 = TIM1_CH1, PWM 输出接 MOS 模块信号输入, MOS 接灯珠回路 */
#define LAMP_RCC           RCC_AHB1Periph_GPIOA
#define LAMP_PORT          GPIOA
#define LAMP_PIN           GPIO_Pin_8
#define LAMP_TIM_RCC       RCC_APB2Periph_TIM1
#define LAMP_TIM           TIM1
#define LAMP_PWM_DUTY_MAX  999               /* 0~999 -> 0~100% */

/* ---------------- DHT11 温湿度 ---------------- */
#define DHT11_RCC          RCC_AHB1Periph_GPIOA
#define DHT11_PORT         GPIOA
#define DHT11_PIN          GPIO_Pin_1

/* ---------------- K230 串口: USART2 PA2(TX)/PA3(RX) ---------------- */
#define K230_BAUD          115200

/* ---------------- ESP-01S 串口: USART3 PB10(TX)/PB11(RX) ---------------- */
/* 注意: 华为云 MQTT 需要 AT 固件 >= 2.0 (支持 AT+MQTT*), 用 AT+GMR 确认 */
#define ESP8266_BAUD       115200

/* ---------------- 华为云 IoTDA 设备接入 ----------------
 * ★ 账号 / 密钥 / 云平台接入信息已统一抽到 USER/secret_config.h，
 *   该文件不进版本库（见 .gitignore）；模板是 USER/secret_config.example.h。
 *   新环境只要把模板复制成 secret_config.h 填上自己的值即可，
 *   本文件与其它源码都不用改。
 *   ★ secret_config.h 里定义了：WIFI_SSID / WIFI_PASS /
 *     IOT_SERVER / IOT_DEVICE_ID / IOT_CLIENT_ID / IOT_PASSWORD / IOT_SERVICE_ID
 *     缺少该文件会编译报错 "cannot open source input file secret_config.h"，
 *     按上面提示复制模板即可。 */
#include "secret_config.h"

#define IOT_PORT           1883              /* 非TLS 1883 / TLS 8883(AT固件1=TCP) */

/* ---------------- 业务参数 ---------------- */
#define DHT11_PERIOD_MS    2000              /* 温湿度采样周期 */
#define REPORT_PERIOD_MS   5000              /* 上报云周期 */

/* ---------------- 按键 ---------------- */
#define KEY_LAMP_RCC       RCC_AHB1Periph_GPIOE
#define KEY_LAMP_PORT      GPIOE
#define KEY_LAMP_PIN       GPIO_Pin_4        /* KEY0: 诱虫灯开关 */
#define KEY_BRIGHT_RCC     RCC_AHB1Periph_GPIOA
#define KEY_BRIGHT_PORT    GPIOA
#define KEY_BRIGHT_PIN     GPIO_Pin_0        /* WK_UP: 循环切换亮度档 */

#endif
