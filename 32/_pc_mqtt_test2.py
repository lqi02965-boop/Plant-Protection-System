# -*- coding: utf-8 -*-
"""用华为云弹窗给的 clientId+HMAC password 验证认证"""
import socket

# 凭据取自私有文件 pc_secret.py（不进版本库，模板见 pc_secret.example.py）
try:
    from pc_secret import CLIENT_ID, USERNAME, PASSWORD
    from pc_secret import IOT_SERVER as HOST, IOT_PORT as PORT
except Exception:
    CLIENT_ID = "your-device-id_0_0_YYYYMMDDHH"
    USERNAME = "your-device-id"
    PASSWORD = "console-generated-hmac-password"
    HOST = "xxxxxxxxxx.st1.iotda-device.cn-north-4.myhuaweicloud.com"
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
