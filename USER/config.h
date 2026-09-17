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

/* ---------------- 华为云 IoTDA 设备接入（按控制台实际值改） ---------------- */
#define IOT_SERVER         "70bddf2542.st1.iotda-device.cn-north-4.myhuaweicloud.com"  /* 标准版实例专属设备接入地址(接入信息->设备接入->MQTT 1883) */
#define IOT_PORT           1883              /* 非TLS 1883 / TLS 8883(AT固件1=TCP) */
#define IOT_DEVICE_ID      "6a83ca9fcbb0cf6bb97a57b0_shebei"   /* 设备ID */
/* 华为云"MQTT连接参数"弹窗给出的配套凭证:
 * clientId 带时间戳, password 为平台计算好的 HMAC —— 二者必须成对使用 */
#define IOT_CLIENT_ID      "6a83ca9fcbb0cf6bb97a57b0_shebei_0_0_2026090603"
#define IOT_PASSWORD       "4d4eddece4c7122a2d93b55d47c02909df33c3d31892782dee036923d16ededa"
#define IOT_SERVICE_ID     "mydeta"          /* 服务ID(与旧版 mqtt.h 产品模型一致) */

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
