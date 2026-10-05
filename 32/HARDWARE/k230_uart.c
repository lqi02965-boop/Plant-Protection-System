#include "k230_uart.h"

/* ============================================================
 * K230 -> STM32 虫数帧:  "$" + 十进制虫数 + "#"
 * 例: $12#  表示当前帧检测到 12 只虫
 * USART2 中断收字节, 主循环里用状态机拼帧, 不在中断里做业务
 * ============================================================ */

static volatile int  g_pest_count = -1;
static volatile uint8_t g_new_flag = 0;

static uint8_t rx_byte;
static char    frame_buf[16];
static uint8_t frame_len = 0;

void K230_Uart_Init(uint32_t baud)
{
    GPIO_InitTypeDef  g;
    USART_InitTypeDef u;
    NVIC_InitTypeDef  n;

    RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOA, ENABLE);
    RCC_APB1PeriphClockCmd(RCC_APB1Periph_USART2, ENABLE);

    GPIO_PinAFConfig(GPIOA, GPIO_PinSource2, GPIO_AF_USART2);
    GPIO_PinAFConfig(GPIOA, GPIO_PinSource3, GPIO_AF_USART2);

    g.GPIO_Pin   = GPIO_Pin_2 | GPIO_Pin_3;
    g.GPIO_Mode  = GPIO_Mode_AF;
    g.GPIO_OType = GPIO_OType_PP;
    g.GPIO_PuPd  = GPIO_PuPd_UP;
    g.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(GPIOA, &g);

    u.USART_BaudRate            = baud;
    u.USART_WordLength          = USART_WordLength_8b;
    u.USART_StopBits            = USART_StopBits_1;
    u.USART_Parity              = USART_Parity_No;
    u.USART_HardwareFlowControl = USART_HardwareFlowControl_None;
    u.USART_Mode                = USART_Mode_Rx | USART_Mode_Tx;
    USART_Init(USART2, &u);

    USART_ITConfig(USART2, USART_IT_RXNE, ENABLE);
    USART_Cmd(USART2, ENABLE);

    n.NVIC_IRQChannel = USART2_IRQn;
    n.NVIC_IRQChannelPreemptionPriority = 1;
    n.NVIC_IRQChannelSubPriority = 1;
    n.NVIC_IRQChannelCmd = ENABLE;
    NVIC_Init(&n);
}

/* 字节由 USART2 中断接收, 中断内直接状态机拼帧,
 * 业务(阈值判断)放主循环, 中断里只更新 g_pest_count */

/* 中断服务: 在 stm32f4xx_it.c 中调用此函数 */
void K230_Uart_IRQHandler(void)
{
    if (USART_GetITStatus(USART2, USART_IT_RXNE) != RESET)
    {
        rx_byte = USART_ReceiveData(USART2) & 0xFF;
        if (rx_byte == '$')
        {
            frame_len = 0;
        }
        else if (rx_byte == '#')
        {
            frame_buf[frame_len < sizeof(frame_buf) - 1 ? frame_len : sizeof(frame_buf) - 1] = '\0';
            if (frame_len > 0)
            {
                int v = 0, ok = 1;
                for (uint8_t i = 0; i < frame_len; i++)
                {
                    if (frame_buf[i] < '0' || frame_buf[i] > '9') { ok = 0; break; }
                    v = v * 10 + (frame_buf[i] - '0');
                }
                if (ok) { g_pest_count = v; g_new_flag = 1; }
            }
            frame_len = 0;
        }
        else if (frame_len < sizeof(frame_buf) - 1)
        {
            frame_buf[frame_len++] = (char)rx_byte;
        }
        else
        {
            frame_len = 0;   /* 超长帧丢弃 */
        }
    }
}

int K230_GetPestCount(void)   { return g_pest_count; }
void K230_ClearCount(void)    { g_pest_count = -1; g_new_flag = 0; }
