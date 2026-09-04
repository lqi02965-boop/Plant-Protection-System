#ifndef _DHT11_H
#define _DHT11_H
#include "stm32f4xx.h"

/* 返回 0 成功; 温度/湿度为放大10倍的整数, 例如 256 = 25.6℃ */
uint8_t DHT11_Init(void);
uint8_t DHT11_Read(uint8_t *temp_x10, uint8_t *humi_x10);

#endif
