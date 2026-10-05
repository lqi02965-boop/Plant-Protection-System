#ifndef _SECRET_CONFIG_H
#define _SECRET_CONFIG_H
/* ============================================================
 * secret_config.h 的【模板】—— 这个文件会提交到仓库，只有占位符。
 *
 * 【怎么用】
 *   把本文件复制一份、去掉 .example，得到 secret_config.h：
 *       Windows:  copy USER\secret_config.example.h USER\secret_config.h
 *       Linux/Mac: cp USER/secret_config.example.h USER/secret_config.h
 *   然后把下面各项换成你自己的值。secret_config.h 已被 .gitignore 忽略，
 *   不会被提交。
 *
 * 【为什么这样拆】
 *   账号、密钥、云平台接入信息属于本机私有配置，不应该进版本库。
 *   源码只 #include "secret_config.h"（见 USER/config.h），
 *   所以换环境时只动这一个文件，代码一行都不用改。
 * ============================================================ */

/* ---------------- WiFi（必须 2.4G，ESP-01S 不支持 5G） ---------------- */
#define WIFI_SSID          "your-wifi-ssid"
#define WIFI_PASS          "your-wifi-password"

/* ---------------- 华为云 IoTDA 设备接入 ----------------
 * IOT_CLIENT_ID 与 IOT_PASSWORD 是"成对"的：
 * 控制台 -> 设备详情 -> MQTT 连接参数 弹窗里给出的那一对，整对复制。
 * IOT_SERVER 用【实例专属】的设备接入域名（接入信息 -> 设备接入 -> MQTT） */
#define IOT_SERVER         "xxxxxxxxxx.st1.iotda-device.cn-north-4.myhuaweicloud.com"
#define IOT_DEVICE_ID      "your-device-id"
#define IOT_CLIENT_ID      "your-device-id_0_0_YYYYMMDDHH"
#define IOT_PASSWORD       "console-generated-hmac-password"
#define IOT_SERVICE_ID     "your-service-id"

#endif
