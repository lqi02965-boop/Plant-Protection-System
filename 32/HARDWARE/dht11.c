#include "dht11.h"
#include "delay.h"
#include "config.h"

/* ============================================================
 * DHT11 单总线时序 (GPIO 开漏模拟, 靠 µs 级高电平宽度区分 0/1)
 * 主机拉低>=18ms 起始 -> 释放总线 -> DHT11 应答 80us低+80us高
 * -> 40bit 数据: 每bit以50us低电平开始, 高电平 26~28us=0 / 70us=1
 * 数据: 湿度整数 湿度小数 温度整数 温度小数 校验和
 * ============================================================ */

static void DHT11_IO_OUT(void)
{
    GPIO_InitTypeDef g;
    g.GPIO_Pin   = DHT11_PIN;
    g.GPIO_Mode  = GPIO_Mode_OUT;
    g.GPIO_OType = GPIO_OType_OD;       /* 开漏 + 外部/内部上拉 */
    g.GPIO_PuPd  = GPIO_PuPd_UP;
    g.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(DHT11_PORT, &g);
}

static void DHT11_IO_IN(void)
{
    GPIO_InitTypeDef g;
    g.GPIO_Pin   = DHT11_PIN;
    g.GPIO_Mode  = GPIO_Mode_IN;
    g.GPIO_PuPd  = GPIO_PuPd_UP;
    GPIO_Init(DHT11_PORT, &g);
}

#define DHT11_DQ_OUT()  DHT11_IO_OUT()
#define DHT11_DQ_IN()   DHT11_IO_IN()
#define DHT11_DQ(x)     GPIO_WriteBit(DHT11_PORT, DHT11_PIN, (BitAction)(x))
#define DHT11_READ()    GPIO_ReadInputDataBit(DHT11_PORT, DHT11_PIN)

uint8_t DHT11_Init(void)
{
    RCC_AHB1PeriphClockCmd(DHT11_RCC, ENABLE);
    DHT11_DQ_OUT();
    DHT11_DQ(1);                        /* 总线空闲为高 */
    delay_ms(10);
    DHT11_DQ_IN();                      /* 切输入上拉, 探测空闲电平 */
    delay_ms(2);
    printf("[DHT11] idle=%d (1=总线正常被上拉, 0=线没接对/模块坏)\r\n",
           DHT11_READ());
    return 0;
}

/* 等待电平变化, 超时返回1 (容差放宽到500us, 兼容慢速兼容颗粒) */
static uint8_t dht_wait(uint8_t level, uint32_t timeout_us)
{
    while (DHT11_READ() != level)
        if (timeout_us-- == 0) return 1;
    return 0;
}

static uint8_t dht_read_byte(void)
{
    uint8_t i, byte = 0;
    for (i = 0; i < 8; i++)
    {
        if (dht_wait(1, 500)) return 0xFF;      /* 等50us低电平结束 */
        delay_us(40);                            /* 40us 后采样: 高=1 低=0 */
        byte <<= 1;
        if (DHT11_READ()) byte |= 1;
        if (dht_wait(0, 500)) return 0xFF;      /* 等本bit高电平结束 */
    }
    return byte;
}

uint8_t DHT11_Read(uint8_t *temp_x10, uint8_t *humi_x10)
{
    uint8_t humi_i, humi_d, temp_i, temp_d, check;

    __disable_irq();    /* 单总线时序敏感, 读取期间屏蔽中断(~4ms) */

    DHT11_DQ_OUT();
    DHT11_DQ(0);
    delay_ms(20);                       /* 起始信号: 拉低 >=18ms */
    DHT11_DQ(1);
    DHT11_DQ_IN();
    delay_us(30);

    if (dht_wait(0, 500)) { __enable_irq(); return 1; }   /* DHT11 应答 80us 低 */
    if (dht_wait(1, 500)) { __enable_irq(); return 2; }   /* 80us 高 */
    if (dht_wait(0, 500)) { __enable_irq(); return 3; }

    humi_i = dht_read_byte();
    humi_d = dht_read_byte();
    temp_i = dht_read_byte();
    temp_d = dht_read_byte();
    check  = dht_read_byte();

    __enable_irq();

    if (check != (uint8_t)(humi_i + humi_d + temp_i + temp_d))
        return 4;                        /* 校验失败 */

    *humi_x10 = humi_i * 10 + humi_d;
    *temp_x10 = temp_i * 10 + (temp_d & 0x7F);
    return 0;
}
