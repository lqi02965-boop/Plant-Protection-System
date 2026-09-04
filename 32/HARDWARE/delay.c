#include "delay.h"

/* 用 DWT(Cortex-M4 内核调试单元)做精确 us 延时, 比 SysTick 不占用系统节拍 */
#define DWT_CTRL    (*(volatile uint32_t *)0xE0001000)
#define DWT_CYCCNT  (*(volatile uint32_t *)0xE0001004)
#define DEM_CR      (*(volatile uint32_t *)0xE000EDFC)

void Delay_Init(void)
{
    DEM_CR |= (1 << 24);            /* TRCENA */
    DWT_CYCCNT = 0;
    DWT_CTRL |= 1;                  /* CYCCNTENA, 168MHz 计数 */
}

void delay_us(uint32_t us)
{
    uint32_t start = DWT_CYCCNT;
    uint32_t ticks = us * (SystemCoreClock / 1000000);
    while ((DWT_CYCCNT - start) < ticks);
}

void delay_ms(uint32_t ms)
{
    while (ms--) delay_us(1000);
}
