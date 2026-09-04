/* ============================================================
 * stm32f4xx_it.c -- 中断服务例程
 *
 * 注意: SysTick_Handler 已在 USER/main.c 中定义, 本文件不能再定义!
 *
 * 串口中断接线(按 32/README.md 要求):
 *   USART2_IRQHandler -> K230_Uart_IRQHandler   (K230 虫数串口 "$n#")
 *   USART3_IRQHandler -> ESP8266_IRQHandler     (ESP-01S 华为云 MQTT URC)
 * ============================================================ */
#include "stm32f4xx.h"
#include "k230_uart.h"
#include "esp8266.h"

/* ---------------- Cortex-M4 内核异常 ---------------- */
void NMI_Handler(void) {}
void HardFault_Handler(void) { while (1) { } }
void MemManage_Handler(void) { while (1) { } }
void BusFault_Handler(void) { while (1) { } }
void UsageFault_Handler(void) { while (1) { } }
void SVC_Handler(void) {}
void DebugMon_Handler(void) {}
void PendSV_Handler(void) {}
/* SysTick_Handler: 已在 main.c 定义, 此处禁止重复定义 */

/* ---------------- USART2: K230 虫数帧 ---------------- */
void USART2_IRQHandler(void)
{
    K230_Uart_IRQHandler();
}

/* ---------------- USART3: ESP-01S 华为云 MQTT ---------------- */
void USART3_IRQHandler(void)
{
    ESP8266_IRQHandler();
}
