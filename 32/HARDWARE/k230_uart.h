#ifndef _K230_UART_H
#define _K230_UART_H
#include "stm32f4xx.h"

void K230_Uart_Init(uint32_t baud);         /* USART2 PA2/PA3 */
void K230_Uart_IRQHandler(void);            /* 在 stm32f4xx_it.c 的 USART2 中断里调用 */
int  K230_GetPestCount(void);               /* 最近一次收到的虫数, -1=未收到 */
void K230_ClearCount(void);

#endif
