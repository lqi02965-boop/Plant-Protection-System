# -*- coding: utf-8 -*-
# =============================================================================
#  pc_secret.py 的【模板】—— 本文件会提交到仓库，只有占位符
#
#  【怎么用】
#    复制本文件、去掉 .example，得到 pc_secret.py，再把值填成你自己的：
#        Windows:   copy pc_secret.example.py pc_secret.py
#        Linux/Mac: cp   pc_secret.example.py pc_secret.py
#    pc_secret.py 已被 .gitignore 忽略，不会被提交。
#
#  这些值从华为云控制台拿：
#    DEVICE_ID / DEVICE_SECRET  -> IoTDA -> 设备 -> 设备详情
#    IOT_SERVER                 -> 接入信息 -> 设备接入 -> MQTT（实例专属域名）
#    CLIENT_ID / PASSWORD       -> 设备详情 ->「MQTT 连接参数」弹窗，整对复制
# =============================================================================

DEVICE_ID     = "your-device-id"
DEVICE_SECRET = "your-device-secret"

IOT_SERVER    = "xxxxxxxxxx.st1.iotda-device.cn-north-4.myhuaweicloud.com"
IOT_PORT      = 1883

CLIENT_ID     = "your-device-id_0_0_YYYYMMDDHH"
USERNAME      = "your-device-id"
PASSWORD      = "console-generated-hmac-password"
