#ifndef _PWM_LAMP_H
#define _PWM_LAMP_H
#include "stm32f4xx.h"

/* 诱虫灯 PWM 调光: 0~100 (亮度百分比), 0=关 */
void Lamp_PWM_Init(void);
void Lamp_Set(uint8_t percent);     /* 0~100 */
uint8_t Lamp_Get(void);

#endif
