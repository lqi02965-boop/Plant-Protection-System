# -*- coding: utf-8 -*-
"""用设备三元组从PC直接发起MQTT连接, 验证华为云是否接受
成功(20 02) => 设备应立即激活/在线 => 问题在设备端
失败        => 返回的错误码说明认证/参数哪里不对"""
import socket
import struct

DEVICE_ID = "6a83ca9fcbb0cf6bb97a57b0_shebei"
SECRET = "09e2d555d80a8354c31e2973883199fdb5ad276ee9c4220e6c21397f5ea641c1"
HOST = "70bddf2542.st1.iotda-device.cn-north-4.myhuaweicloud.com"
PORT = 1883

def remain_len(n):
    out = b""
    while True:
        b = n % 128
        n //= 128
        if n > 0:
            b |= 0x80
        out += bytes([b])
        if n == 0:
            return out

def build_connect():
    cid = DEVICE_ID + "_0_0"
    payload = (bytes([0, len(cid)]) + cid.encode()
               + bytes([0, len(DEVICE_ID)]) + DEVICE_ID.encode()
               + bytes([0, len(SECRET)]) + SECRET.encode())
    body = (bytes([0, 4]) + b"MQTT" + bytes([4])          # 协议名 MQTT level4
            + bytes([0xC2]) + bytes([0, 100]) + payload)   # flags, keepalive
    return bytes([0x10]) + remain_len(len(body)) + body

pkt = build_connect()
print("CONNECT %d bytes" % len(pkt))

s = socket.create_connection((HOST, PORT), timeout=10)
s.sendall(pkt)
data = s.recv(64)
print("收到 %d 字节:" % len(data), data.hex())
if len(data) >= 2 and data[0] == 0x20:
    code = data[1] if data[1] != 2 else (data[3] if len(data) > 3 else 0)
    if data[1] == 0x02:
        print(">>> CONNACK 接受! 设备应已激活/在线 <<<")
    else:
        print(">>> 被拒绝, 返回码:", hex(data[1]), "(4=用户名密码错, 5=未授权)")
s.close()
