/* ============================================================
 * STM32F407VET6 -- 农田虫害智能监测系统 主控端
 * 标准库 + Keil5, ST-Link 下载
 *
 * 业务闭环（泵已取消）:
 *   K230 --USART2 "$虫数#"--> 计数
 *   DHT11 定时采样温湿度
 *   TIM1_CH1 PWM -> MOS模块 -> 诱虫灯亮度调节 (KEY0 开关 / WK_UP 换档 / 云下发)
 *   ESP-01S --MQTT--> 华为云 IoTDA 上报属性 + 接收命令
 *   小程序(华为云北向API) 查看数据 / 下发亮度命令
 * ============================================================ */
#include "stm32f4xx.h"
#include "delay.h"
#include "config.h"
#include "dht11.h"
#include "pwm_lamp.h"
#include "k230_uart.h"
#include "esp8266.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

/* -------- WiFi 配置, 按现场改 -------- */
#define WIFI_SSID     "xxq"
#define WIFI_PASS     "liqi5334"

/* 非 static: esp8266.c 判下行"空闲间隔"要用这个毫秒计数 */
volatile uint32_t g_sys_ms = 0;

void SysTick_Handler(void)
{
    g_sys_ms++;
}

/* 按键: KEY0 灯开关(低有效), WK_UP 循环亮度档(高有效) */
#define KEY_LAMP_DOWN()    (GPIO_ReadInputDataBit(KEY_LAMP_PORT, KEY_LAMP_PIN) == Bit_RESET)
#define KEY_BRIGHT_DOWN()  (GPIO_ReadInputDataBit(KEY_BRIGHT_PORT, KEY_BRIGHT_PIN) == Bit_SET)

static void keys_init(void)
{
    GPIO_InitTypeDef g;
    RCC_AHB1PeriphClockCmd(KEY_LAMP_RCC | KEY_BRIGHT_RCC, ENABLE);

    g.GPIO_Mode = GPIO_Mode_IN;
    g.GPIO_Pin  = KEY_LAMP_PIN;
    g.GPIO_PuPd = GPIO_PuPd_UP;
    GPIO_Init(KEY_LAMP_PORT, &g);

    g.GPIO_Pin  = KEY_BRIGHT_PIN;
    g.GPIO_PuPd = GPIO_PuPd_DOWN;
    GPIO_Init(KEY_BRIGHT_PORT, &g);
}

/* 调试串口: USART1 PA9/PA10 板载 CH340 */
static void debug_usart1_init(void)
{
    GPIO_InitTypeDef  g;
    USART_InitTypeDef u;

    RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOA, ENABLE);
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_USART1, ENABLE);

    GPIO_PinAFConfig(GPIOA, GPIO_PinSource9,  GPIO_AF_USART1);
    GPIO_PinAFConfig(GPIOA, GPIO_PinSource10, GPIO_AF_USART1);

    g.GPIO_Pin = GPIO_Pin_9 | GPIO_Pin_10;
    g.GPIO_Mode = GPIO_Mode_AF;
    g.GPIO_OType = GPIO_OType_PP;
    g.GPIO_PuPd = GPIO_PuPd_UP;
    GPIO_Init(GPIOA, &g);

    u.USART_BaudRate = 115200;
    u.USART_WordLength = USART_WordLength_8b;
    u.USART_StopBits = USART_StopBits_1;
    u.USART_Parity = USART_Parity_No;
    u.USART_Mode = USART_Mode_Rx | USART_Mode_Tx;
    USART_Init(USART1, &u);
    USART_Cmd(USART1, ENABLE);
}

int fputc(int ch, FILE *f)
{
    USART_SendData(USART1, (uint8_t)ch);
    while (USART_GetFlagStatus(USART1, USART_FLAG_TXE) == RESET);
    return ch;
}

/* ---------------- 云侧命令处理(解析由 Net_GetCommand 完成) ---------------- */
static uint8_t g_lamp_on = 0;
static uint8_t g_brightness = 60;

/* ---------------- 上报华为云属性(透传MQTT) ---------------- */
static uint8_t report_to_cloud(uint8_t temp_x10, uint8_t humi_x10, int pests)
{
    return Net_Publish(temp_x10, humi_x10, (pests < 0 ? 0 : pests),
                       g_lamp_on, g_brightness);
}

int main(void)
{
    uint32_t last_dht_ms = 0, last_report_ms = 0;
    uint8_t  temp_x10 = 0, humi_x10 = 0;
    uint8_t  lamp_key_prev = 0, bright_key_prev = 0;
    int      last_pest = 0;     /* 最近一次 K230 报来的虫数（跨循环保持，供周期上报用） */
    static const uint8_t bright_steps[4] = {25, 50, 75, 100};
    uint8_t  step_idx = 1;      /* 默认 50% */
		debug_usart1_init();
    /* ===== 启动自检: 裸延时闪烁 PA8 三次, 不依赖任何外设/时钟配置 =====
     * 复位后看到闪三下 => CPU在执行main, 问题在串口通路/外设;
     * 完全不闪 => 程序根本没执行, 查 BOOT0 跳线/供电 */
    {
        GPIO_InitTypeDef g;
        volatile uint32_t d;
        int i;
        RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOA, ENABLE);
        g.GPIO_Pin   = GPIO_Pin_8;
        g.GPIO_Mode  = GPIO_Mode_OUT;
        g.GPIO_OType = GPIO_OType_PP;
        g.GPIO_PuPd  = GPIO_PuPd_NOPULL;
        g.GPIO_Speed = GPIO_Speed_2MHz;
        GPIO_Init(GPIOA, &g);
        for (i = 0; i < 6; i++)
        {
            GPIO_ToggleBits(GPIOA, GPIO_Pin_8);
            for (d = 0; d < 1500000; d++) { }   /* ~0.1s 裸延时 */
        }
    }

    Delay_Init();
    SysTick_Config(SystemCoreClock / 1000);
    //debug_usart1_init();
    printf("\r\n=== pest monitor boot (cloud ver) ===\r\n");

    keys_init();
    Lamp_PWM_Init();
    DHT11_Init();
    K230_Uart_Init(K230_BAUD);

    Lamp_Set(g_brightness);
    g_lamp_on = 1;

    /* 组网: WiFi -> TCP透传 -> MQTT登录 -> 订阅 (内部自动重试) */
    Net_Init(WIFI_SSID, WIFI_PASS);

    uint32_t last_heart_ms = 0;
    uint8_t  net_fail_cnt = 0;

    while (1)
    {
        uint32_t now = g_sys_ms;

        /* 1. 定时采温湿度 */
        if (now - last_dht_ms >= DHT11_PERIOD_MS)
        {
            last_dht_ms = now;
            uint8_t dht_err = DHT11_Read(&temp_x10, &humi_x10);
            if (dht_err == 0)
                printf("T=%u.%u H=%u.%u\r\n", temp_x10 / 10, temp_x10 % 10,
                       humi_x10 / 10, humi_x10 % 10);
            else
                printf("[DHT11] err=%u (1/2/3=无应答查接线, 4=校验错)\r\n", dht_err);
        }

        /* 2. K230 虫数帧 */
        int pest = K230_GetPestCount();
        if (pest >= 0)
        {
            last_pest = pest;       /* ★ 记到 last_pest：上报时用它，别用本轮临时值 */
            printf("pest=%d\r\n", pest);
            /* 虫数只记录上报; 如需"虫多自动亮灯/拉满亮度"逻辑在此扩展 */
            K230_ClearCount();
        }

        /* 3. 按键: KEY0 开关灯, WK_UP 循环亮度档 */
        uint8_t l = KEY_LAMP_DOWN(), b = KEY_BRIGHT_DOWN();
        if (l && !lamp_key_prev)
        {
            g_lamp_on = !g_lamp_on;
            Lamp_Set(g_lamp_on ? g_brightness : 0);
        }
        lamp_key_prev = l;
        if (b && !bright_key_prev)
        {
            step_idx = (step_idx + 1) % 4;
            g_brightness = bright_steps[step_idx];
            if (!g_lamp_on) g_lamp_on = 1;
            Lamp_Set(g_brightness);
        }
        bright_key_prev = b;

        /* 4. 云命令(透传MQTT下行, Net_GetCommand 内部已回执) */
        uint8_t cmd_on = g_lamp_on, cmd_bright = g_brightness;
        if (Net_GetCommand(&cmd_on, &cmd_bright))
        {
            g_lamp_on = cmd_on;
            g_brightness = cmd_bright;
            Lamp_Set(g_lamp_on ? g_brightness : 0);
            printf("cloud cmd -> on=%u bright=%u\r\n", g_lamp_on, g_brightness);
        }

        /* 5. MQTT 心跳(keepalive 100s, 30s 发一次保险) */
        if (now - last_heart_ms >= 30000)
        {
            last_heart_ms = now;
            net_fail_cnt += Net_Heartbeat();
            Net_PrintStats();       /* 诊断: 收字节/溢出/下行包 */
        }

        /* 6. 周期上报华为云 */
        if (now - last_report_ms >= REPORT_PERIOD_MS)
        {
            last_report_ms = now;
            net_fail_cnt += report_to_cloud(temp_x10, humi_x10, last_pest);
        }

        /* 7. 连续失败说明链路已死, 整链重建(WiFi->TCP->MQTT登录->订阅) */
        if (net_fail_cnt >= 3)
        {
            net_fail_cnt = 0;
            printf("[net] link dead, full reconnect...\r\n");
            Net_Init(WIFI_SSID, WIFI_PASS);
            last_heart_ms = g_sys_ms;
            last_report_ms = g_sys_ms;
        }
    }
}
