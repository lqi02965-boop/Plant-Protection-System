// ====== 华为云 IoT 配置【模板】—— 本文件会提交到仓库，只有占位符 ======
//
// 【怎么用】
//   把本文件复制一份、去掉 .example，得到 config.js：
//       Windows:   copy config.example.js config.js
//       Linux/Mac: cp config.example.js config.js
//   然后把下面各项换成你自己的值。config.js 已被 .gitignore 忽略，不会被提交。
//
// 【这些值从华为云哪里拿】
//   region        IoTDA 实例所在区域，如 cn-north-4
//   appEndpoint   实例专属【应用接入】地址（IoTDA -> 实例 -> 接入信息 -> 应用接入 -> HTTPS）
//   projectId     我的凭证 -> 项目列表 -> 对应区域的项目ID
//   domainName    IAM 主账号名
//   iamUser       IAM 子用户名（建议专门建一个只用于本项目的子用户）
//   iamPass       该子用户的密码
//   deviceId      IoTDA -> 设备 -> 设备ID
//   serviceId     产品模型里的服务ID（要和设备端 config.h 的 IOT_SERVICE_ID 一致）
module.exports = {
  region: 'cn-north-4',
  appEndpoint: 'xxxxxxxxxx.st1.iotda-app.cn-north-4.myhuaweicloud.com',
  projectId: 'your-iam-project-id',
  domainName: 'your-iam-domain-name',
  iamUser: 'your-iam-username',
  iamPass: 'your-iam-password',
  deviceId: 'your-device-id',
  serviceId: 'your-service-id'
}
