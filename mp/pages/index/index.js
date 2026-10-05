const iot = require('../../utils/huawei.js')

Page({
  data: {
    temp: '--',
    humi: '--',
    pests: '--',
    lampOn: false,
    brightness: 50,
    online: false,
    lastUpdate: '',
    refreshing: false
  },

  onLoad() {
    this.refresh()
    // 定时轮询设备属性(5s)
    this.timer = setInterval(() => this.refresh(), 5000)
  },

  onShow() {
    // 从设置页返回时配置可能已变更, 立即刷新
    this.refresh()
  },

  onUnload() {
    clearInterval(this.timer)
  },

  refresh() {
    if (this.data.refreshing) return
    this.setData({ refreshing: true })
    iot.queryProperties()
      .then(p => {
        const patch = {
          temp: p.temp != null ? Number(p.temp).toFixed(1) : '--',
          humi: p.humi != null ? Number(p.humi).toFixed(1) : '--',
          pests: p.pests != null ? String(p.pests) : '--',
          online: true,
          lastUpdate: this.timeNow()
        }
        // 刚下发过命令的几秒内不要用云端旧值覆盖本地控件,
        // 否则滑条/开关会"自己弹回去"(云侧影子要等设备下次上报才更新)
        if (!this.cmdHoldUntil || Date.now() > this.cmdHoldUntil) {
          patch.lampOn = !!p.lamp_on
          patch.brightness = p.brightness != null ? p.brightness : 50
        }
        this.setData(patch)
        if (!p._reported) {
          wx.showToast({ title: '云已连上, 设备还没上报过数据', icon: 'none' })
        }
      })
      .catch(err => {
        console.error(err)
        this.setData({ online: false })
        wx.showToast({ title: '云端连接失败', icon: 'none' })
      })
      .then(() => this.setData({ refreshing: false }))
  },

  onLampToggle(e) {
    const on = e.detail.value
    this.setData({ lampOn: on })
    this.cmdHoldUntil = Date.now() + 8000
    wx.showLoading({ title: '下发中...', mask: true })
    iot.sendLampCommand(on, this.data.brightness)
      .then(() => {
        wx.hideLoading()
        wx.showToast({ title: '已下发', icon: 'success' })
      })
      .catch(err => {
        wx.hideLoading()
        console.error(err)
        wx.showToast({ title: '下发失败', icon: 'none' })
        this.setData({ lampOn: !on })
        this.cmdHoldUntil = 0
      })
  },

  onBrightnessChange(e) {
    const v = e.detail.value
    this.setData({ brightness: v, lampOn: v > 0 })
    this.cmdHoldUntil = Date.now() + 8000
    // 拖动结束才发命令, 防刷屏
    if (this.brightTimer) clearTimeout(this.brightTimer)
    this.brightTimer = setTimeout(() => {
      iot.sendLampCommand(v > 0, v)
        .then(() => wx.showToast({ title: '亮度 ' + v + '%', icon: 'none' }))
        .catch(err => {
          console.error(err)
          wx.showToast({ title: '下发失败', icon: 'none' })
          this.cmdHoldUntil = 0
        })
    }, 400)
  },

  goSetting() {
    wx.navigateTo({ url: '/pages/setting/setting' })
  },

  timeNow() {
    const d = new Date()
    const p = n => (n < 10 ? '0' + n : '' + n)
    return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds())
  }
})
