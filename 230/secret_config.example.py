# -*- coding: utf-8 -*-
# =============================================================================
#  secret_config.py 的【模板】—— 本文件会提交到仓库，只有占位符
#
#  【怎么用】
#    1) 复制本文件、去掉 .example，得到 secret_config.py：
#         Windows:   copy secret_config.example.py secret_config.py
#         Linux/Mac: cp   secret_config.example.py secret_config.py
#    2) 填上你的 2.4G WiFi
#       （K230 无线模块不支持 5G；密码里不能有英文双引号）
#    3) 把它放到板子上：/sdcard/secret_config.py
#       —— CanMV IDE 的文件面板可以直接往板子里保存文件（不需要联网）；
#          也可以用 board_recv.py 从电脑推上去。
#
#  main.py / board_check.py / board_recv.py / get_files.py / ai_dump.py
#  都用 `from secret_config import WLAN_SSID, WLAN_PASS` 读取，
#  所以 WiFi 凭据只需要维护这一份，源码里不再留任何真实密码。
#
#  注：若板子上没有这个文件，各脚本会回退到占位值（只影响联网/推流，
#      K230 的检测、LCD 显示、串口上报照常工作）。
# =============================================================================

WLAN_SSID = "your_wifi_ssid"     # 2.4G WiFi 名
WLAN_PASS = "your_wifi_pass"     # WiFi 密码
