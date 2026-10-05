const iot = require('../../utils/huawei.js')

// 表单字段定义: key/label/占位提示
const FIELDS = [
  { key: 'region',      label: '区域',          placeholder: '如 cn-north-4', required: true },
  { key: 'appEndpoint', label: '应用接入域名',  placeholder: 'IoTDA实例-接入信息-应用接入-HTTPS(443)', required: true },
  { key: 'projectId',   label: 'IAM 项目ID',    placeholder: '我的凭证->项目列表', required: true },
  { key: 'domainName',  label: 'IAM 域名',      placeholder: '主账号名', required: true },
  { key: 'iamUser',     label: 'IAM 用户名',    placeholder: 'IAM子用户或主账号名', required: true },
  { key: 'iamPass',     label: 'IAM 密码',      placeholder: '对应用户密码', required: true, password: true },
  { key: 'deviceId',    label: '设备ID',        placeholder: 'IoTDA设备列表里的设备ID', required: true },
  { key: 'serviceId',   label: '服务ID',        placeholder: '产品模型服务ID, 如 mydeta', required: false }
]

Page({
  data: {
    fields: FIELDS,
    form: {},
    usingCustom: false
  },

  onLoad() {
    // 用生效配置(默认值+已存覆盖)回填表单
    const eff = iot.loadConfig()
    const form = {}
    FIELDS.forEach(f => { form[f.key] = eff[f.key] || '' })
    this.setData({
      form,
      usingCustom: Object.keys(iot.getSavedRaw()).length > 0
    })
  },

  onInput(e) {
    const key = e.currentTarget.dataset.key
    this.setData({ ['form.' + key]: e.detail.value })
  },

  save() {
    const form = this.data.form
    for (const f of FIELDS) {
      if (f.required && !(form[f.key] || '').trim()) {
        wx.showToast({ title: '请填写: ' + f.label, icon: 'none' })
        return
      }
    }
    iot.saveConfig(form)
    this.setData({ usingCustom: true })
    // 保存后立即试查一次设备影子, 验证配置是否可用
    wx.showLoading({ title: '正在验证配置...' })
    iot.queryProperties()
      .then(() => {
        wx.hideLoading()
        wx.showToast({ title: '配置有效 ✓', icon: 'success' })
        setTimeout(() => wx.navigateBack(), 800)
      })
      .catch(err => {
        wx.hideLoading()
        wx.showModal({
          title: '配置已保存, 但验证失败',
          content: String(err.message || err).slice(0, 300),
          showCancel: false
        })
      })
  },

  reset() {
    wx.showModal({
      title: '恢复默认',
      content: '清除本机保存的云配置, 恢复为 App 内置默认值?',
      success: res => {
        if (res.confirm) {
          iot.clearSavedConfig()
          const eff = iot.loadConfig()
          const form = {}
          FIELDS.forEach(f => { form[f.key] = eff[f.key] || '' })
          this.setData({ form, usingCustom: false })
          wx.showToast({ title: '已恢复默认', icon: 'success' })
        }
      }
    })
  }
})
