// 华为云 IoTDA 北向 API 封装
// 配置优先级: 本地缓存(设置页填写) > config.js 默认值
// 数据流: STM32 -> ESP8266(MQTT) -> IoTDA 云 -> 本小程序查属性/下发命令
// 认证: IAM 用户名密码换 token -> 带 X-Subject-Token 调 IoTDA API
// 小程序内 wx.request 域名需在mp后台配置 request 合法域名,
// 开发阶段可在开发者工具勾选"不校验合法域名"直接调试

const defaultConfig = require('../config.js')

const CFG_KEY = 'huawei_cloud_cfg'
let tokenCache = { token: '', expire: 0, user: '' }

// 读取生效配置(缓存覆盖默认值)
function loadConfig() {
  let saved = {}
  try {
    saved = wx.getStorageSync(CFG_KEY) || {}
  } catch (e) { saved = {} }
  const cfg = Object.assign({}, defaultConfig, saved)
  // 去掉未填写的字段, 避免空串覆盖默认值
  Object.keys(cfg).forEach(k => {
    if (cfg[k] === '' || cfg[k] == null) delete cfg[k]
  })
  return cfg
}

// 设置页保存/清除配置后调用: 配置变了, 旧 token 必须作废重取
function saveConfig(cfg) {
  const clean = {}
  Object.keys(cfg).forEach(k => {
    const v = (cfg[k] || '').toString().trim()
    if (v !== '') clean[k] = v
  })
  wx.setStorageSync(CFG_KEY, clean)
  clearToken()
}

function clearSavedConfig() {
  wx.removeStorageSync(CFG_KEY)
  clearToken()
}

function getSavedRaw() {
  try { return wx.getStorageSync(CFG_KEY) || {} } catch (e) { return {} }
}

function clearToken() {
  tokenCache = { token: '', expire: 0, user: '' }
}

function iamToken(cfg) {
  return new Promise((resolve, reject) => {
    const now = Date.now()
    const userKey = cfg.domainName + '/' + cfg.iamUser
    if (tokenCache.token && now < tokenCache.expire && tokenCache.user === userKey) {
      resolve(tokenCache.token)
      return
    }
    wx.request({
      url: 'https://iam.myhuaweicloud.com/v3/auth/tokens',
      method: 'POST',
      data: {
        auth: {
          identity: {
            methods: ['password'],
            password: {
              user: {
                domain: { name: cfg.domainName },
                name: cfg.iamUser,
                password: cfg.iamPass
              }
            }
          },
          scope: { project: { name: cfg.region } }
        }
      },
      header: { 'Content-Type': 'application/json' },
      success(res) {
        const t = res.header['X-Subject-Token'] || res.header['x-subject-token']
        if (t) {
          tokenCache = { token: t, expire: now + 20 * 3600 * 1000, user: userKey } // token 24h,缓存20h
          resolve(t)
        } else {
          reject(new Error('IAM 认证失败: ' + JSON.stringify(res.data)))
        }
      },
      fail: reject
    })
  })
}

function iotRequest(method, path, data) {
  const cfg = loadConfig()
  return iamToken(cfg).then(token => {
    return new Promise((resolve, reject) => {
      wx.request({
        // 标准版实例必须用实例专属应用接入域名, 通用域名路由不到你的实例
        url: 'https://' + cfg.appEndpoint + path,
        method: method,
        data: data,
        header: {
          'Content-Type': 'application/json',
          'X-Auth-Token': token
        },
        success: res => {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            // 华为云业务失败时也返回 HTTP 200 + error_code(如 IOTDA.014111 命令超时),
            // 必须显式判错, 否则会被当成功、弹出"已下发"骗人
            if (res.data && res.data.error_code) {
              reject(new Error(res.data.error_code + ' ' + (res.data.error_msg || '')))
            } else {
              resolve(res.data)
            }
          } else {
            reject(new Error(res.statusCode + ' ' + JSON.stringify(res.data)))
          }
        },
        fail: reject
      })
    })
  })
}

// 查询设备影子(离线也能读到最近一次上报的属性)
// 实时属性接口在设备离线时会报 IOTDA.014016, 所以小程序必须走影子
function queryProperties() {
  const cfg = loadConfig()
  return iotRequest('GET',
    '/v5/iot/' + cfg.projectId + '/devices/' + cfg.deviceId + '/shadow')
    .then(data => {
      const props = {}
      let reported = false
      ;(data.shadow || []).forEach(s => {
        // 优先取设备上报值(reported), 没有再用期望值(desired)
        const rep = s.reported && Object.keys(s.reported.properties || {}).length
        const src = rep ? s.reported : s.desired
        if (rep) reported = true
        Object.assign(props, (src && src.properties) || {})
      })
      props._reported = reported          // 是否有设备上报过数据
      return props
    })
}

// 下发命令: set_lamp paras={lamp_on:0/1, brightness:0~100}
function sendLampCommand(lampOn, brightness) {
  const cfg = loadConfig()
  return iotRequest('POST',
    '/v5/iot/' + cfg.projectId + '/devices/' + cfg.deviceId + '/commands',
    {
      service_id: cfg.serviceId,
      command_name: 'set_lamp',
      paras: { lamp_on: lampOn ? 1 : 0, brightness: brightness }
    })
}

module.exports = {
  loadConfig, saveConfig, clearSavedConfig, getSavedRaw,
  clearToken, queryProperties, sendLampCommand
}
