# 微信小程序端（手机端，替代原 PC 上位机）

功能：显示温度/湿度/虫子数量、诱虫灯开关和**亮度**调节（PWM），数据经华为云 IoTDA 中转，5 秒自动刷新。

## 目录

| 文件 | 说明 |
|------|------|
| `config.js` | 华为云配置（区域/项目ID/IAM账号/设备ID），**需要你填** |
| `utils/huawei.js` | IAM 换 token → IoTDA 查属性 / 下发命令 |
| `pages/index/` | 主页面：数据卡片 + 灯开关 + 亮度滑条 |

## 需要你从华为云拿的数据（填到 `config.js`）

1. **开通 IoTDA**：华为云控制台搜"IoT设备接入"（标准版，区域建议 cn-north-4）
2. **创建产品**：协议 MQTT；产品模型里建服务 `PestMonitor`，属性：
   `temp(float) humi(float) pests(int) lamp_on(int) brightness(int)`
3. **创建设备**：得到 **设备ID** 和 **设备密钥**（密钥给 STM32 端 config.h 用）
4. **IAM 项目ID**：控制台"我的凭证"→ 项目列表里对应区域的项目 ID
5. **IAM 用户名/密码/域名**（主账号名或子用户），小程序调 API 用

>STM32 端还要填 MQTT 接入地址（`config.h` 的 `IOT_SERVER`，控制台"总览-接入信息"里看，如 `iot-mqtts.cn-north-4.myhuaweicloud.com`）。

## 运行

1. 微信开发者工具导入本 `mp/` 目录（测试号即可，appid 用占位）
2. 右上角"详情→本地设置"勾选 **不校验合法域名**（开发阶段）
3. 正式上线前在小程序后台把 `iotda.cn-north-4.myhuaweicloud.com`、`iam.myhuaweicloud.com` 加为 request 合法域名

## 数据链路

```
设备上报: STM32 --MQTT--> $oc/devices/{id}/sys/properties/report  (设备侧)
小程序读: GET /v5/iot/{projectId}/devices/{deviceId}/properties     (应用侧API)
小程序控: POST /v5/iot/{projectId}/devices/{deviceId}/commands      (命令 set_lamp)
设备执行: STM32 订阅 $oc/devices/{id}/sys/commands/# 收到后调 PWM
```

## 面试要点

- **为什么需要云平台**：小程序无法监听端口收 TCP，设备侧 MQTT 上行 + 应用侧 REST API 查询/下发是标准物联网"物模型"架构
- **设备侧 vs 应用侧**：设备用三元组 MQTT 接入，应用用 IAM token 走 HTTPS API
- 华为 IoTDA 属性上报/命令下发的 `$oc` 主题体系和 JSON 转义（AT 指令里引号要 `\\\"`）
