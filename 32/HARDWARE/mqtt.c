#include "mqtt.h"
#include "config.h"
#include <string.h>

/* ============================================================
 * MQTT 报文手工组包(不再直接操作串口, 发送交给网络层)
 * ============================================================ */

/* 剩余长度变长编码, 写入 buf 从 pos 起, 返回写入字节数 */
static uint8_t mqtt_remain_len(uint16_t len, uint8_t *buf, uint8_t pos)
{
    do
    {
        uint8_t b = len % 128;
        len /= 128;
        if (len > 0) b |= 0x80;
        buf[pos++] = b;
    } while (len > 0);
    return pos;
}

uint16_t MQTT_BuildConnect(uint8_t *buf)
{
    uint16_t pos = 0, remain;
    const char *cid   = IOT_DEVICE_ID "_0_0";
    const char *user  = IOT_DEVICE_ID;
    const char *pass  = IOT_DEVICE_SECRET;
    uint8_t cid_l = strlen(cid), user_l = strlen(user), pass_l = strlen(pass);

    remain = 10 + (cid_l + 2) + (user_l + 2) + (pass_l + 2);

    buf[pos++] = 0x10;                            /* CONNECT */
    pos = mqtt_remain_len(remain, buf, pos);
    buf[pos++] = 0x00; buf[pos++] = 0x04;         /* 协议名长度 */
    buf[pos++] = 'M';  buf[pos++] = 'Q';
    buf[pos++] = 'T';  buf[pos++] = 'T';
    buf[pos++] = 0x04;                            /* Level 4 */
    buf[pos++] = 0xC2;                            /* User+Pass+CleanSession */
    buf[pos++] = 0x00; buf[pos++] = 0x64;         /* keepalive 100s */
    buf[pos++] = 0x00; buf[pos++] = cid_l;
    memcpy(&buf[pos], cid, cid_l);   pos += cid_l;
    buf[pos++] = 0x00; buf[pos++] = user_l;
    memcpy(&buf[pos], user, user_l); pos += user_l;
    buf[pos++] = 0x00; buf[pos++] = pass_l;
    memcpy(&buf[pos], pass, pass_l); pos += pass_l;
    return pos;
}

uint16_t MQTT_BuildSubscribe(uint8_t *buf, uint8_t msg_id, const char *topic)
{
    uint16_t pos = 0, remain;
    uint8_t tl = strlen(topic);

    remain = 2 + (tl + 2) + 1;

    buf[pos++] = 0x82;                            /* SUBSCRIBE */
    pos = mqtt_remain_len(remain, buf, pos);
    buf[pos++] = 0x00; buf[pos++] = msg_id;
    buf[pos++] = 0x00; buf[pos++] = tl;
    memcpy(&buf[pos], topic, tl); pos += tl;
    buf[pos++] = 0x00;                            /* QoS0 */
    return pos;
}

uint16_t MQTT_BuildPublish(uint8_t *buf, const char *topic, const char *json)
{
    uint16_t pos = 0, remain;
    uint8_t tl = strlen(topic);
    uint16_t jl = strlen(json);

    remain = (tl + 2) + jl;

    buf[pos++] = 0x30;                            /* PUBLISH QoS0 */
    pos = mqtt_remain_len(remain, buf, pos);
    buf[pos++] = 0x00; buf[pos++] = tl;
    memcpy(&buf[pos], topic, tl); pos += tl;
    memcpy(&buf[pos], json, jl); pos += jl;
    return pos;
}

uint16_t MQTT_BuildPing(uint8_t *buf)
{
    buf[0] = 0xC0;                                /* PINGREQ */
    buf[1] = 0x00;
    return 2;
}
