#ifndef _ESP8266_H
#define _ESP8266_H
#include "stm32f4xx.h"

/* ============================================================
 * ESP8266 网络层 (AT固件1.x兼容方案)
 * 思路: AT+CIPSTART 建TCP -> AT+CIPMODE=1+CIPSEND 进入透传
 *       -> STM32 上直接组 MQTT 协议包透传给华为云 1883
 * (ESP-01S 老固件1.7.4 无 AT+MQTT 指令, 故不用 AT MQTT 方案)
 * ============================================================ */

/* 阻塞式组网: 退出透传->AT->RST->WiFi->TCP->透传->MQTT登录->订阅
 * ssid/pass: 现场 WiFi; 失败自动重试(串口有进度打印) */
void Net_Init(const char *ssid, const char *pass);

/* 主循环轮询: 收敛下行数据, 解析云命令(lamp_on/brightness)
 * 返回1=有新命令, 参数带回; 内部已回执华为云 */
uint8_t Net_GetCommand(uint8_t *lamp_on, uint8_t *brightness);

/* 发布属性上报到 $oc/.../properties/report
 * temp_x10/humi_x10: 放大10倍的整数; pests: 虫数(-1表示未知) */
void Net_Publish(uint8_t temp_x10, uint8_t humi_x10, int pests,
                 uint8_t lamp_on, uint8_t brightness);

/* MQTT 心跳(保活), 主循环周期调用 */
void Net_Heartbeat(void);

/* USART3 中断服务入口, 由 stm32f4xx_it.c 调用 */
void ESP8266_IRQHandler(void);

#endif
