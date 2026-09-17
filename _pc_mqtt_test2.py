# -*- coding: utf-8 -*-
"""用华为云弹窗给的 clientId+HMAC password 验证认证"""
import socket

CLIENT_ID = "6a83ca9fcbb0cf6bb97a57b0_shebei_0_0_2026090603"
USERNAME = "6a83ca9fcbb0cf6bb97a57b0_shebei"
PASSWORD = "4d4eddece4c7122a2d93b55d47c02909df33c3d31892782dee036923d16ededa"
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
    payload = (bytes([0, len(CLIENT_ID)]) + CLIENT_ID.encode()
               + bytes([0, len(USERNAME)]) + USERNAME.encode()
               + bytes([0, len(PASSWORD)]) + PASSWORD.encode())
    body = bytes([0, 4]) + b"MQTT" + bytes([4]) + bytes([0xC2]) + bytes([0, 100]) + payload
    return bytes([0x10]) + remain_len(len(body)) + body

s = socket.create_connection((HOST, PORT), timeout=10)
s.sendall(build_connect())
data = s.recv(64)
print("收到:", data.hex())
if data[0] == 0x20 and data[3] == 0x00:
    print(">>> 认证成功(返回码00)! 设备应已激活 <<<")
else:
    print(">>> 拒绝, 返回码:", hex(data[3]))
s.close()
