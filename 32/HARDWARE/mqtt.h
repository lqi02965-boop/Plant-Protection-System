#ifndef _MQTT_H
#define _MQTT_H
#include "stm32f4xx.h"

/* ============================================================
 * MQTT 3.1.1 协议组包层(纯组包, 发送由网络层 AT+CIPSEND=<len> 完成)
 * 华为云认证: clientId={device_id}_0_0, username={device_id},
 *            password={secret}(时间戳0免HMAC, 见config.h)
 * 返回报文总长度(固定头+剩余长度+载荷)
 * ============================================================ */

uint16_t MQTT_BuildConnect(uint8_t *buf);
uint16_t MQTT_BuildSubscribe(uint8_t *buf, uint8_t msg_id, const char *topic);
uint16_t MQTT_BuildPublish(uint8_t *buf, const char *topic, const char *json);
uint16_t MQTT_BuildPing(uint8_t *buf);

#endif
