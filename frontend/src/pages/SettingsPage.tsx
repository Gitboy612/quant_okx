import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Save, RefreshCw } from 'lucide-react'
import { getSettings, saveSettings } from '../api/settings'
import type { UserSettings } from '../types'

export default function SettingsPage() {
  const [settings, setSettings] = useState<UserSettings>({ refresh_interval: '30' })
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    getSettings().then((res) => setSettings(res.data)).catch(() => {})
  }, [])

  const handleSave = async () => {
    setLoading(true)
    try {
      await saveSettings({ refresh_interval: settings.refresh_interval })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {}
    setLoading(false)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-[#E8E8ED]">系统设置</h2>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-[#14141A] rounded-lg border border-[#1E1E28] p-5 max-w-lg"
      >
        <div className="space-y-4">
          <div>
            <label className="block text-sm text-[#E8E8ED] mb-2">资产自动刷新间隔（秒）</label>
            <p className="text-xs text-[#6B6B7B] mb-3">仪表盘资产余额自动拉取的间隔时间，设为 0 则关闭自动刷新</p>
            <input
              type="number"
              min={0}
              max={3600}
              value={settings.refresh_interval}
              onChange={(e) => setSettings({ ...settings, refresh_interval: e.target.value })}
              className="w-32 bg-[#0C0C14] border border-[#1E1E28] rounded-lg px-4 py-2.5 text-sm text-[#E8E8ED] focus:outline-none focus:border-[#00D4AA] transition-colors"
            />
          </div>

          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={handleSave}
              disabled={loading}
              className="flex items-center gap-2 bg-[#00D4AA] text-[#0A0A0F] rounded-lg px-5 py-2.5 text-sm font-semibold hover:bg-[#00D4AA]/90 disabled:opacity-50 transition-colors"
            >
              <Save className="w-4 h-4" />
              {loading ? '保存中...' : '保存设置'}
            </button>
            {saved && (
              <motion.span
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="text-xs text-[#00D4AA]"
              >
                已保存
              </motion.span>
            )}
          </div>
        </div>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="bg-[#14141A] rounded-lg border border-[#1E1E28] p-5 max-w-lg"
      >
        <h3 className="text-xs text-[#6B6B7B] mb-3 uppercase tracking-wide">说明</h3>
        <div className="text-sm text-[#6B6B7B] space-y-2">
          <p>自动刷新运行在前端浏览器中，页面关闭即停止。</p>
          <p>刷新间隔过短可能触发 OKX API 频率限制，建议不低于 10 秒。</p>
        </div>
      </motion.div>
    </div>
  )
}
