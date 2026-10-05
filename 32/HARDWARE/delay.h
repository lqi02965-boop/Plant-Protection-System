#ifndef _DELAY_H
#define _DELAY_H
#include "stm32f4xx.h"

void Delay_Init(void);          /* 使能 DWT 周期计数器 */
void delay_us(uint32_t us);     /* DWT 精确微秒延时 */
void delay_ms(uint32_t ms);

#endif
