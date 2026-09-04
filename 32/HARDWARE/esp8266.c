#include "esp8266.h"
#include "mqtt.h"
#include "delay.h"
#include "config.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

/* ============================================================
 * ESP8266 网络层 (API模式 AT+CIPSEND=<len>, 兼容AT固件1.x)
 * 发送: 每包 CIPSEND 指定长度, ESP 回 "Recv N bytes"+"OK" 有回执
 * 接收: 服务器数据以 "+IPD,len:数据" 形式到达, 中断收进 recv_buf
 * ============================================================ */

#define RECV_BUF_SIZE 512

static char     recv_buf[RECV_BUF_SIZE];
static volatile uint8_t recv_cnt = 0;
static uint8_t  recv_pre = 0;

/* USART3 发送 */
static void net_send_str(const char *s)
{
    while (*s)
    {
        USART_SendData(USART3, (uint8_t)*s++);
        while (USART_GetFlagStatus(USART3, USART_FLAG_TXE) == RESET);
    }
    while (USART_GetFlagStatus(USART3, USART_FLAG_TC) == RESET);
}

static void net_send_bytes(const uint8_t *buf, uint16_t len)
{
    while (len--)
    {
        USART_SendData(USART3, *buf++);
        while (USART_GetFlagStatus(USART3, USART_FLAG_TXE) == RESET);
    }
    while (USART_GetFlagStatus(USART3, USART_FLAG_TC) == RESET);
}

static void recv_clear(void)
{
    recv_cnt = 0;
    recv_pre = 0;
    memset(recv_buf, 0, RECV_BUF_SIZE);
}

static void recv_end(void)
{
    recv_buf[recv_cnt < RECV_BUF_SIZE ? recv_cnt : RECV_BUF_SIZE - 1] = '\0';
}

/* 发 AT 指令并等待应答含 expect; 超时打印原始应答 */
static uint8_t net_cmd(const char *cmd, const char *expect, uint16_t timeout_10ms)
{
    uint16_t t = timeout_10ms;
    recv_clear();
    net_send_str(cmd);
    while (t--)
    {
        delay_ms(10);
        if (recv_cnt > 0 && recv_cnt == recv_pre)
        {
            recv_end();
            if (expect[0] == '\0' || strstr(recv_buf, expect) != NULL)
            {
                recv_clear();
                return 0;
            }
        }
        recv_pre = recv_cnt;
    }
    recv_end();
    printf("[AT-FAIL] %.20s | len=%u resp:%.60s\r\n", cmd, recv_cnt, recv_buf);
    return 1;
}

/* 在接收缓冲里找连续两字节 (CONNACK/SUBACK/PINGRESP 二进制特征) */
static uint8_t recv_contains(uint8_t a, uint8_t b)
{
    uint8_t i;
    for (i = 0; i + 1 < recv_cnt; i++)
        if ((uint8_t)recv_buf[i] == a && (uint8_t)recv_buf[i + 1] == b)
            return 1;
    return 0;
}

/* USART3 中断 (由 stm32f4xx_it.c 调用) */
void ESP8266_IRQHandler(void)
{
    if (USART_GetFlagStatus(USART3, USART_FLAG_ORE) != RESET)
    {
        USART_ReceiveData(USART3);      /* 读SR+DR 清 ORE, 否则从此收不到 */
        return;
    }
    if (USART_GetITStatus(USART3, USART_IT_RXNE) != RESET)
    {
        uint8_t b = (uint8_t)USART_ReceiveData(USART3);
        if (recv_cnt < RECV_BUF_SIZE - 1)
            recv_buf[recv_cnt++] = (char)b;
    }
}

/* TCP 连云 (可重入) */
static uint8_t net_tcp_connect(void)
{
    char cmd[128];
    uint8_t retry = 0;

    snprintf(cmd, sizeof(cmd), "AT+CIPSTART=\"TCP\",\"%s\",%u\r\n",
             IOT_SERVER, IOT_PORT);
    while (net_cmd(cmd, "CONNECT", 300))
    {
        printf("[net] tcp retry %u\r\n", ++retry);
        delay_ms(1000);
    }
    printf("[net] tcp OK\r\n");
    return 0;
}

/* API 模式发送一个 MQTT 报文: CIPSEND=<len> -> '>' -> 数据 -> "OK" */
static uint8_t net_mqtt_send(const uint8_t *pkt, uint16_t len)
{
    char hdr[24];
    uint8_t retry = 0;

    snprintf(hdr, sizeof(hdr), "AT+CIPSEND=%u\r\n", len);
    for (;;)
    {
        recv_clear();
        net_send_str(hdr);
        /* 等 '>' 提示符(2s) */
        {
            uint16_t t = 200;
            uint8_t got = 0;
            while (t--)
            {
                delay_ms(10);
                if (recv_cnt > 0 && recv_cnt == recv_pre)
                {
                    recv_end();
                    if (strchr(recv_buf, '>') != NULL) { got = 1; break; }
                    if (strstr(recv_buf, "ERROR") != NULL || strstr(recv_buf, "CLOSED") != NULL)
                        break;
                }
                recv_pre = recv_cnt;
            }
            if (!got)
            {
                printf("[mqtt-tx] no '>' len=%u resp:%.40s\r\n", recv_cnt, recv_buf);
                return 1;
            }
        }
        net_send_bytes(pkt, len);
        /* 等发送回执 "OK" (2s) */
        {
            uint16_t t = 200;
            while (t--)
            {
                delay_ms(10);
                if (recv_cnt > 0 && recv_cnt == recv_pre)
                {
                    recv_end();
                    if (strstr(recv_buf, "OK") != NULL)
                    {
                        recv_clear();
                        return 0;
                    }
                    if (strstr(recv_buf, "ERROR") != NULL || strstr(recv_buf, "CLOSED") != NULL)
                        break;
                }
                recv_pre = recv_cnt;
            }
        }
        printf("[mqtt-tx] no OK, len=%u resp:%.40s\r\n", recv_cnt, recv_buf);
        if (++retry >= 2)
            return 1;
        delay_ms(500);
    }
}

/* USART3 硬件初始化 */
static void usart3_init(uint32_t baud)
{
    GPIO_InitTypeDef  g;
    USART_InitTypeDef u;
    NVIC_InitTypeDef  n;

    RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOB, ENABLE);
    RCC_APB1PeriphClockCmd(RCC_APB1Periph_USART3, ENABLE);

    GPIO_PinAFConfig(GPIOB, GPIO_PinSource10, GPIO_AF_USART3);
    GPIO_PinAFConfig(GPIOB, GPIO_PinSource11, GPIO_AF_USART3);

    g.GPIO_Pin   = GPIO_Pin_10 | GPIO_Pin_11;
    g.GPIO_Mode  = GPIO_Mode_AF;
    g.GPIO_OType = GPIO_OType_PP;
    g.GPIO_PuPd  = GPIO_PuPd_UP;
    g.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(GPIOB, &g);

    u.USART_BaudRate            = baud;
    u.USART_WordLength          = USART_WordLength_8b;
    u.USART_StopBits            = USART_StopBits_1;
    u.USART_Parity              = USART_Parity_No;
    u.USART_HardwareFlowControl = USART_HardwareFlowControl_None;
    u.USART_Mode                = USART_Mode_Rx | USART_Mode_Tx;
    USART_Init(USART3, &u);

    USART_ITConfig(USART3, USART_IT_RXNE, ENABLE);
    USART_Cmd(USART3, ENABLE);

    n.NVIC_IRQChannel = USART3_IRQn;
    n.NVIC_IRQChannelPreemptionPriority = 2;
    n.NVIC_IRQChannelSubPriority = 1;
    n.NVIC_IRQChannelCmd = ENABLE;
    NVIC_Init(&n);

    delay_ms(500);
}

void Net_Init(const char *ssid, const char *pass)
{
    char cmd[128];
    uint8_t retry;

    usart3_init(ESP8266_BAUD);
    printf("[net] init esp8266...\r\n");

    /* 1. AT 握手 */
    retry = 0;
    while (net_cmd("AT\r\n", "OK", 20) && ++retry < 20)
    {
        printf("[net] waiting esp8266...\r\n");
        delay_ms(500);
    }

    /* 2. 重启 + 基础配置 */
    net_cmd("AT+RST\r\n", "", 30);
    delay_ms(2000);
    net_cmd("ATE0\r\n", "OK", 20);          /* 关回显 */
    net_cmd("AT+CIPMUX=0\r\n", "OK", 20);   /* 单连接 */
    net_cmd("AT+CIPMODE=0\r\n", "OK", 20);  /* 普通传输模式(非透传) */

    /* 3. WiFi (连接耗时5s+, 超时10s) */
    while (net_cmd("AT+CWMODE_CUR=1\r\n", "OK", 30))
        delay_ms(500);
    snprintf(cmd, sizeof(cmd), "AT+CWJAP=\"%s\",\"%s\"\r\n", ssid, pass);
    retry = 0;
    while (net_cmd(cmd, "GOT IP", 1000))
    {
        printf("[net] join ap retry %u\r\n", ++retry);
        delay_ms(1000);
    }
    printf("[net] wifi OK\r\n");

    /* 4. TCP */
    net_tcp_connect();

    /* 5. MQTT 登录, 等 CONNACK (20 02) */
    {
        uint8_t pkt[256];
        uint16_t len = MQTT_BuildConnect(pkt);
        retry = 0;
        for (;;)
        {
            recv_clear();
            if (net_mqtt_send(pkt, len) == 0)
            {
                delay_ms(2000);
                if (recv_contains(0x20, 0x02))
                {
                    printf("[net] mqtt login OK\r\n");
                    break;
                }
            }
            printf("[net] mqtt login retry %u, len=%u resp:%.40s\r\n", ++retry, recv_cnt, recv_buf);
            if (retry % 3 == 0)
            {
                printf("[net] link recovery...\r\n");
                net_cmd("AT+CIPCLOSE\r\n", "", 50);
                net_tcp_connect();
            }
            delay_ms(500);
        }
    }

    /* 6. 订阅命令主题, 等 SUBACK (0x90) */
    {
        static const char *cands[] = {
            "$oc/devices/" IOT_DEVICE_ID "/sys/commands/#",
            "$oc/devices/" IOT_DEVICE_ID "/sys/commands/request_id=+",
            "$oc/devices/" IOT_DEVICE_ID "/sys/messages/down",
        };
        uint8_t pkt[192];
        uint8_t ci = 0;
        retry = 0;
        for (;;)
        {
            uint16_t len = MQTT_BuildSubscribe(pkt, (uint8_t)(ci + 1), cands[ci]);
            recv_clear();
            if (net_mqtt_send(pkt, len) == 0)
            {
                delay_ms(2000);
                if (recv_contains(0x90, 0x00) || recv_contains(0x90, 0x01) ||
                    recv_contains(0x90, 0x02) || recv_contains(0x90, 0x80))
                {
                    printf("[net] subscribe OK (cand %u)\r\n", ci);
                    break;
                }
            }
            printf("[net] subscribe cand %u retry %u, len=%u resp:%.40s\r\n",
                   ci, ++retry, recv_cnt, recv_buf);
            if (++ci >= 3)
                ci = 0;
            if (retry % 3 == 0)
            {
                printf("[net] link recovery...\r\n");
                net_cmd("AT+CIPCLOSE\r\n", "", 50);
                net_tcp_connect();
            }
            delay_ms(500);
        }
    }
}

/* 从 +IPD 数据里提取 request_id 并回执 result_code */
static void net_send_command_response(void)
{
    char rid[40] = {0};
    const char *p = strstr(recv_buf, "request_id=");
    uint8_t i = 0;
    if (p == NULL)
        return;
    p += 11;
    while (*p && *p != '{' && i < sizeof(rid) - 1)
    {
        /* topic 结束于长度边界, '+' 或 '{' 之后的即 payload */
        if (*p == '"') break;
        rid[i++] = *p++;
    }
    rid[i] = '\0';
    if (i == 0)
        return;
    {
        uint8_t pkt[192];
        char rtopic[128];
        char body[] = "{\"result_code\":0}";
        snprintf(rtopic, sizeof(rtopic),
                 "$oc/devices/" IOT_DEVICE_ID "/sys/commands/response/request_id=%s", rid);
        uint16_t len = MQTT_BuildPublish(pkt, rtopic, body);
        net_mqtt_send(pkt, len);
    }
}

/* 主循环轮询: +IPD 数据稳定后解析云命令 */
uint8_t Net_GetCommand(uint8_t *lamp_on, uint8_t *brightness)
{
    const char *p;
    uint8_t new_cmd = 0;

    if (recv_cnt == 0)
    {
        recv_pre = 0;
        return 0;
    }
    if (recv_cnt != recv_pre)
    {
        recv_pre = recv_cnt;
        return 0;
    }

    recv_end();

    p = strstr(recv_buf, "brightness");
    if (p)
        p = strchr(p, ':');
    if (p)
    {
        int v = atoi(p + 1);
        if (v < 0) v = 0;
        if (v > 100) v = 100;
        *brightness = (uint8_t)v;
        *lamp_on = (*brightness > 0);
        new_cmd = 1;
    }
    p = strstr(recv_buf, "lamp_on");
    if (p)
        p = strchr(p, ':');
    if (p)
    {
        int v = atoi(p + 1);
        *lamp_on = (v != 0);
        new_cmd = 1;
    }

    if (new_cmd)
    {
        net_send_command_response();
        printf("[net] cloud cmd parsed on=%u bright=%u\r\n", *lamp_on, *brightness);
    }

    recv_clear();
    return new_cmd;
}

void Net_Publish(uint8_t temp_x10, uint8_t humi_x10, int pests,
                 uint8_t lamp_on, uint8_t brightness)
{
    char json[192];
    uint8_t pkt[288];
    snprintf(json, sizeof(json),
             "{\"services\":[{\"service_id\":\"" IOT_SERVICE_ID "\","
             "\"properties\":{\"temp\":%u.%u,\"humi\":%u.%u,"
             "\"pests\":%d,\"lamp_on\":%u,\"brightness\":%u}}]}",
             temp_x10 / 10, temp_x10 % 10, humi_x10 / 10, humi_x10 % 10,
             (pests < 0 ? 0 : pests), lamp_on, brightness);
    {
        uint16_t len = MQTT_BuildPublish(pkt,
            "$oc/devices/" IOT_DEVICE_ID "/sys/properties/report", json);
        if (net_mqtt_send(pkt, len) != 0)
            printf("[net] publish fail\r\n");
    }
}

void Net_Heartbeat(void)
{
    uint8_t pkt[4];
    uint16_t len = MQTT_BuildPing(pkt);
    net_mqtt_send(pkt, len);
}
