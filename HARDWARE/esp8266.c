#include "esp8266.h"
#include "mqtt.h"
#include "delay.h"
#include "config.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

/* ============================================================
 * ESP8266 网络层 (API模式 AT+CIPSEND=<len>, 兼容AT固件1.x)
 * 发送: 每包 CIPSEND 指定长度, ESP 回 "SEND OK" 才算发出
 * 接收: 服务器数据以 "+IPD,len:数据" 到达, 中断里抽到独立缓冲
 *
 * ★ 云端命令收不到的根因与修法(实测定位):
 *   旧版把 AT 回显和下行 MQTT 报文塞进同一个 recv_buf, 主循环又用
 *   "连续两圈内容不变 = 收完了" 当判据。但主循环是微秒级空转, 而串口
 *   一个字节要 87us —— 缓冲里刚进 1 个字节, 下一圈就被判定"收完",
 *   立刻 dump + recv_clear()。现象就是云命令到达时串口刷出:
 *       [net] RX(len=1): 76 / RX(len=1): 62 / RX(len=1): 6D ...
 *   整条 +IPD 报文被一个字节一个字节地拆碎丢光, 云侧只能报
 *   IOTDA.014111 Command request timed out。
 *
 *   现在:
 *   1) 中断里用状态机把 +IPD,<len>:<data> 的 data 抽进 ipd_buf,
 *      与主循环节奏完全解耦(碎片到达、慢速到达都不怕);
 *   2) 解析判据改成"距最后一个字节的空闲 >120ms";
 *   3) 按 MQTT PUBLISH 结构定位主题/载荷, 精确取 request_id;
 *   4) CIPSEND 发出数据后先清 recv_buf, 只认之后的 "SEND OK",
 *      修掉"拿上一条 CIPSEND 的 OK 冒充发送成功"→ 撞车 "busy s..."。
 * ============================================================ */

#define RECV_BUF_SIZE 512      /* AT 回显文本缓冲 */
#define IPD_BUF_SIZE  512      /* 下行 MQTT 报文缓冲 */

extern volatile uint32_t g_sys_ms;      /* main.c 的毫秒计数(SysTick) */

static char     recv_buf[RECV_BUF_SIZE];
static volatile uint16_t recv_cnt = 0;

static uint8_t  ipd_buf[IPD_BUF_SIZE];
static volatile uint16_t ipd_len = 0;
static volatile uint32_t ipd_last_ms = 0;

/* 统计量(排查丢字节用) */
static volatile uint32_t rx_total = 0, ore_total = 0, ipd_total = 0;

/* +IPD 抽取状态机(在中断里跑) */
static uint8_t  ipd_st = 0;             /* 0=找"+IPD,"  1=读长度  2=抄载荷 */
static uint8_t  ipd_tok_i = 0;
static uint16_t ipd_need = 0, ipd_cur = 0;
static const char ipd_tok[] = "+IPD,";

/* ---------------- USART3 发送 ---------------- */
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
    recv_buf[0] = '\0';
}

static void recv_end(void)
{
    uint16_t n = recv_cnt < RECV_BUF_SIZE ? recv_cnt : RECV_BUF_SIZE - 1;
    recv_buf[n] = '\0';
}

/* 清空下行报文缓冲(调用前需已关 RXNE 中断, 或确认当前不在收包中) */
static void ipd_clear(void)
{
    ipd_len = 0;
    ipd_st = 0;
    ipd_tok_i = 0;
    ipd_need = 0;
    ipd_cur = 0;
}

/* 下载缓冲里是否存在连续两字节(用于 CONNACK 20 02 / SUBACK 90 03) */
static uint8_t ipd_contains(uint8_t a, uint8_t b)
{
    uint16_t i;
    uint8_t  hit = 0;
    USART_ITConfig(USART3, USART_IT_RXNE, DISABLE);
    for (i = 0; i + 1 < ipd_len; i++)
    {
        if (ipd_buf[i] == a && ipd_buf[i + 1] == b) { hit = 1; break; }
    }
    USART_ITConfig(USART3, USART_IT_RXNE, ENABLE);
    return hit;
}

/* 发 AT 指令并轮询等待应答含 expect; 超时打印原始应答 */
static uint8_t net_cmd(const char *cmd, const char *expect, uint16_t timeout_10ms)
{
    uint16_t t;
    recv_clear();
    net_send_str(cmd);
    for (t = 0; t < timeout_10ms; t++)
    {
        delay_ms(10);
        recv_end();
        if (expect[0] == '\0')
        {
            if (recv_cnt > 0) { recv_clear(); return 0; }   /* 仅需延时/冲刷的场合 */
            continue;
        }
        if (strstr(recv_buf, expect) != NULL)
        {
            recv_clear();
            return 0;
        }
    }
    recv_end();
    printf("[AT-FAIL] %.20s | len=%u resp:%.60s\r\n", cmd, recv_cnt, recv_buf);
    return 1;
}

/* USART3 中断 */
void ESP8266_IRQHandler(void)
{
    uint8_t b, consumed = 0;

    if (USART_GetFlagStatus(USART3, USART_FLAG_ORE) != RESET)
    {
        USART_ReceiveData(USART3);      /* 读SR+DR 清 ORE, 否则从此收不到 */
        ore_total++;
        return;
    }
    if (USART_GetITStatus(USART3, USART_IT_RXNE) == RESET)
        return;

    b = (uint8_t)USART_ReceiveData(USART3);
    rx_total++;

    /* ---- 状态机: 从字节流里剥出 +IPD,<len>:<data> ---- */
    switch (ipd_st)
    {
    case 0:     /* 匹配 "+IPD," */
        if (b == (uint8_t)ipd_tok[ipd_tok_i])
        {
            consumed = 1;
            if (++ipd_tok_i >= 5) { ipd_st = 1; ipd_tok_i = 0; ipd_need = 0; }
        }
        else if (b == '+')
        {
            ipd_tok_i = 1;
            consumed = 1;
        }
        else
        {
            ipd_tok_i = 0;
        }
        break;

    case 1:     /* 读长度直到 ':' */
        consumed = 1;
        if (b >= '0' && b <= '9')
        {
            ipd_need = (uint16_t)(ipd_need * 10 + (b - '0'));
            if (ipd_need > 2000) ipd_need = 2000;
        }
        else if (b == ':')
        {
            ipd_st = 2;
            ipd_cur = 0;
        }
        else
        {
            ipd_st = 0;                     /* 异常, 重新找 */
            ipd_tok_i = 0;
        }
        break;

    case 2:     /* 抄载荷 */
        consumed = 1;
        if (ipd_len < IPD_BUF_SIZE - 1)
        {
            ipd_buf[ipd_len++] = b;
            ipd_last_ms = g_sys_ms;
        }
        if (++ipd_cur >= ipd_need)
        {
            ipd_st = 0;
            ipd_tok_i = 0;
            ipd_total++;
        }
        break;
    }

    /* 非 +IPD 的字节才进 AT 文本缓冲(避免下行报文污染 "OK" 判定) */
    if (!consumed && recv_cnt < RECV_BUF_SIZE - 1)
        recv_buf[recv_cnt++] = (char)b;
}

/* TCP 连云 (可重入) */
static uint8_t net_tcp_connect(void)
{
    char cmd[128];
    uint8_t retry = 0;

    snprintf(cmd, sizeof(cmd), "AT+CIPSTART=\"TCP\",\"%s\",%u\r\n",
             IOT_SERVER, IOT_PORT);

    for (;;)
    {
        uint16_t t;
        uint8_t  ok = 0;

        recv_clear();
        net_send_str(cmd);
        for (t = 0; t < 500; t++)               /* 5s */
        {
            delay_ms(10);
            recv_end();
            if (strstr(recv_buf, "CONNECT") != NULL && strstr(recv_buf, "OK") != NULL)
            {
                ok = 1;
                break;
            }
            if (strstr(recv_buf, "FAIL") != NULL || strstr(recv_buf, "ERROR") != NULL ||
                strstr(recv_buf, "CLOSED") != NULL || strstr(recv_buf, "busy") != NULL)
                break;
        }
        if (ok)
        {
            printf("[net] tcp OK\r\n");
            return 0;
        }
        if (strstr(recv_buf, "ALREADY CONNECTED") != NULL)
        {
            net_cmd("AT+CIPCLOSE\r\n", "", 50);
            delay_ms(300);
            continue;
        }
        printf("[net] tcp retry %u (%.40s)\r\n", ++retry, recv_buf);
        delay_ms(1000);
    }
}

/* API 模式发送一个 MQTT 报文: CIPSEND=<len> -> '>' -> 数据 -> "SEND OK"
 * 只清 AT 文本缓冲, 不动 ipd_buf(下行命令可能在发送期间到达) */
static uint8_t net_mqtt_send(const uint8_t *pkt, uint16_t len)
{
    char hdr[24];
    uint8_t retry = 0;

    snprintf(hdr, sizeof(hdr), "AT+CIPSEND=%u\r\n", len);

    for (;;)
    {
        uint16_t t;
        uint8_t  got = 0;

        /* --- 1. 等 '>' 提示符 --- */
        recv_clear();
        net_send_str(hdr);
        for (t = 0; t < 300; t++)               /* 3s (busy 时放宽) */
        {
            delay_ms(10);
            recv_end();
            if (strchr(recv_buf, '>') != NULL) { got = 1; break; }
            if (strstr(recv_buf, "busy") != NULL) break;
            if (strstr(recv_buf, "ERROR") != NULL || strstr(recv_buf, "CLOSED") != NULL) break;
        }
        if (!got)
        {
            printf("[mqtt-tx] no '>' len=%u resp:%.40s\r\n", len, recv_buf);
            if (++retry >= 5)
                return 1;
            delay_ms(300);                      /* ESP 忙, 缓一下再试 */
            continue;
        }

        /* --- 2. 发数据, 然后清掉 CIPSEND 阶段的 "OK"/">" 残留 ---
         *    否则下面的 strstr(.."OK") 会被上一条 CIPSEND 的 OK 命中,
         *    提前返回"成功", ESP 还在发送中就被下一条 CIPSEND 撞成 busy s... */
        net_send_bytes(pkt, len);
        recv_clear();

        /* --- 3. 等 "SEND OK" --- */
        for (t = 0; t < 300; t++)
        {
            delay_ms(10);
            recv_end();
            if (strstr(recv_buf, "SEND OK") != NULL)
                return 0;
            if (strstr(recv_buf, "ERROR") != NULL || strstr(recv_buf, "CLOSED") != NULL) break;
        }
        printf("[mqtt-tx] no SEND OK, len=%u resp:%.40s\r\n", len, recv_buf);
        if (++retry >= 3)
            return 1;
        delay_ms(300);
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

/* MQTT 登录: 发 CONNECT 后 3s 内等 CONNACK(20 02)
 * 返回0=成功; 1=发送失败; 2=无应答(调用方应重连TCP再重登) */
static uint8_t net_mqtt_login(void)
{
    uint8_t pkt[256];
    uint16_t len = MQTT_BuildConnect(pkt);
    uint16_t t;

    USART_ITConfig(USART3, USART_IT_RXNE, DISABLE);
    ipd_clear();
    USART_ITConfig(USART3, USART_IT_RXNE, ENABLE);

    if (net_mqtt_send(pkt, len) != 0)
        return 1;
    for (t = 0; t < 300; t++)
    {
        delay_ms(10);
        if (ipd_contains(0x20, 0x02))
            return 0;
    }
    return 2;
}

void Net_Init(const char *ssid, const char *pass)
{
    char cmd[128];
    uint8_t retry;

    usart3_init(ESP8266_BAUD);
    printf("[net] init esp8266...\r\n");

    /* 0. ★ 兜底恢复：ESP 可能卡在"等 CIPSEND 数据"的半途状态
     *    场景：上一次运行中刚发完 AT+CIPSEND=<len>、还没发完数据，STM32 就被复位了。
     *    此时 ESP 仍在等那 len 个字节，会把我们随后发的 AT 指令当成业务数据全部吞掉，
     *    表现就是 len=0、一条 AT 都不回（AT+RST 也没用，因为它压根没被当命令解析）。
     *    对策：先灌足够多的填充字节（\r\n 系列，即使被当命令也只是无害的空命令），
     *          把上次的发送计数走完，ESP 就会自动回到命令模式，再重发 AT 即可。
     */
    {
        int i;
        for (i = 0; i < 128; i++)          /* 128 × "\r\n" = 256 字节 */
        {
            net_send_str("\r\n");
            if ((i & 15) == 0) delay_ms(10);
        }
        delay_ms(200);
        recv_clear();
    }

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

    /* 5. MQTT 登录: 3s 轮询等 CONNACK; 失败必重连TCP再重登(防重复CONNECT违规) */
    {
        uint8_t rty = 0;
        for (;;)
        {
            uint8_t r = net_mqtt_login();
            if (r == 0)
            {
                printf("[net] mqtt login OK\r\n");
                break;
            }
            printf("[net] mqtt login retry %u (r=%u)\r\n", ++rty, r);
            net_cmd("AT+CIPCLOSE\r\n", "", 50);
            net_tcp_connect();
            delay_ms(500);
        }
    }

    /* 6. 订阅命令主题, 等 SUBACK (90 03); 失败自愈时必须重新登录 */
    {
        static const char *cands[] = {
            "$oc/devices/" IOT_DEVICE_ID "/sys/commands/#",
            "$oc/devices/" IOT_DEVICE_ID "/sys/commands/request_id=+",
            "$oc/devices/" IOT_DEVICE_ID "/sys/messages/down",
        };
        uint8_t pkt[192];
        uint8_t ci = 0;
        uint8_t rty = 0;
        for (;;)
        {
            uint16_t len = MQTT_BuildSubscribe(pkt, (uint8_t)(ci + 1), cands[ci]);
            uint16_t t;
            uint8_t got = 0;

            USART_ITConfig(USART3, USART_IT_RXNE, DISABLE);
            ipd_clear();
            USART_ITConfig(USART3, USART_IT_RXNE, ENABLE);

            if (net_mqtt_send(pkt, len) == 0)
            {
                for (t = 0; t < 300; t++)       /* 3s 等 SUBACK */
                {
                    delay_ms(10);
                    if (ipd_contains(0x90, 0x03))
                    {
                        got = 1;
                        break;
                    }
                }
                if (got)
                {
                    printf("[net] subscribe OK (cand %u)\r\n", ci);
                    break;
                }
            }
            printf("[net] subscribe cand %u retry %u, ipd=%u resp:%.40s\r\n",
                   ci, ++rty, ipd_len, recv_buf);
            if (++ci >= 3)
                ci = 0;
            /* 无会话/断链: 重连TCP + 重新登录, 再继续订阅 */
            printf("[net] link recovery...\r\n");
            net_cmd("AT+CIPCLOSE\r\n", "", 50);
            net_tcp_connect();
            if (net_mqtt_login() != 0)
                printf("[net] re-login fail, will retry\r\n");
            delay_ms(500);
        }
    }
}

/* 回执云命令: 向 $oc/devices/<id>/sys/commands/response/request_id=<rid> 发 result_code */
static void net_send_command_response(const char *rid)
{
    uint8_t pkt[192];
    char rtopic[160];
    char body[] = "{\"result_code\":0}";
    uint16_t len;
    const char *r = (rid && rid[0]) ? rid : "0";

    snprintf(rtopic, sizeof(rtopic),
             "$oc/devices/" IOT_DEVICE_ID "/sys/commands/response/request_id=%s", r);
    len = MQTT_BuildPublish(pkt, rtopic, body);
    net_mqtt_send(pkt, len);
}

/* 把下行报文以十六进制打出来(前 64 字节) */
static void dump_ipd(uint16_t n)
{
    uint16_t i, m = n < 64 ? n : 64;
    printf("[net] IPD(len=%u): ", n);
    for (i = 0; i < m; i++)
        printf("%02X ", ipd_buf[i]);
    printf("\r\n");
}

/* 主循环轮询: 下行报文完整且空闲后解析云命令(内部已回执) */
uint8_t Net_GetCommand(uint8_t *lamp_on, uint8_t *brightness)
{
    uint8_t  new_cmd = 0;
    char     rid[48];
    uint16_t pend, pstart = 0;
    uint8_t  parsed = 0;

    rid[0] = '\0';

    if (ipd_len == 0)
        return 0;

    /* ★ 空口判据: 距最后一个字节空闲 >120ms 才算收完(主循环是微秒级, 不能用"两圈不变") */
    if (ipd_st != 0 || (uint32_t)(g_sys_ms - ipd_last_ms) < 120)
        return 0;

    USART_ITConfig(USART3, USART_IT_RXNE, DISABLE);

    pend = ipd_len;
    if (pend > IPD_BUF_SIZE - 1) pend = IPD_BUF_SIZE - 1;

    /* --- 按 MQTT PUBLISH 结构定位主题与载荷 --- */
    if (pend > 4 && (ipd_buf[0] >> 4) == 0x03)
    {
        uint16_t q = 1, tl = 0;
        while (q < pend && (ipd_buf[q] & 0x80)) q++;    /* 剩余长度变长编码 */
        if (q < pend) q++;
        if (q + 2 <= pend)
        {
            tl = (uint16_t)(((uint16_t)ipd_buf[q] << 8) | ipd_buf[q + 1]);
            q += 2;
            if ((uint32_t)q + tl <= pend)
            {
                uint16_t i;
                for (i = q; i + 11 < q + tl; i++)        /* 主题里找 request_id= */
                {
                    if (memcmp(&ipd_buf[i], "request_id=", 11) == 0)
                    {
                        uint16_t k = 0;
                        i += 11;
                        while (i < q + tl && k < sizeof(rid) - 1)
                            rid[k++] = (char)ipd_buf[i++];
                        rid[k] = '\0';
                        break;
                    }
                }
                pstart = (uint16_t)(q + tl);
                if ((ipd_buf[0] & 0x06) != 0)            /* QoS>0 还有 2 字节报文ID */
                    pstart += 2;
                parsed = 1;
            }
        }
    }
    if (!parsed)
        pstart = 0;

    /* 载荷区里 0x00 换成 '.' 再当文本搜(MQTT 头里本来就有 0x00) */
    {
        uint16_t i;
        for (i = pstart; i < pend; i++)
            if (ipd_buf[i] == 0x00) ipd_buf[i] = (uint8_t)'.';
        ipd_buf[pend] = 0;
    }

    if (parsed && pstart < pend)
    {
        const char *p = strstr((const char *)&ipd_buf[pstart], "brightness");
        if (p != NULL) p = strchr(p, ':');
        if (p != NULL)
        {
            int v = atoi(p + 1);
            if (v < 0) v = 0;
            if (v > 100) v = 100;
            *brightness = (uint8_t)v;
            *lamp_on = (*brightness > 0);
            new_cmd = 1;
        }
        p = strstr((const char *)&ipd_buf[pstart], "lamp_on");
        if (p != NULL) p = strchr(p, ':');
        if (p != NULL)
        {
            *lamp_on = (atoi(p + 1) != 0);
            new_cmd = 1;
        }
    }

    if (!new_cmd && parsed)
        dump_ipd(pend);                 /* 不是命令就打出原文, 便于排查 */

    ipd_clear();
    USART_ITConfig(USART3, USART_IT_RXNE, ENABLE);

    if (new_cmd)
    {
        printf("[net] cloud cmd parsed on=%u bright=%u rid=%.32s\r\n",
               *lamp_on, *brightness, rid);
        net_send_command_response(rid);
    }
    return new_cmd;
}

uint8_t Net_Publish(uint8_t temp_x10, uint8_t humi_x10, int pests,
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
        {
            printf("[net] publish fail\r\n");
            return 1;
        }
    }
    return 0;
}

uint8_t Net_Heartbeat(void)
{
    uint8_t pkt[4];
    uint16_t len = MQTT_BuildPing(pkt);
    return net_mqtt_send(pkt, len);
}

/* 诊断: 打印收字节/溢出/下行包统计 */
void Net_PrintStats(void)
{
    printf("[net] stats rx=%lu ore=%lu ipd=%lu\r\n",
           (unsigned long)rx_total, (unsigned long)ore_total, (unsigned long)ipd_total);
}
