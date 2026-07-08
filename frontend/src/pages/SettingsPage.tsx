import { useEffect, useState, useRef } from 'react'
import { motion } from 'framer-motion'
import { Save, Upload, Wifi, CheckCircle, XCircle, Loader2, Lock, Play, Square, Server } from 'lucide-react'
import { getSettings, saveSettings, getProxySettings, saveProxySettings, testProxy, importProxyConfig, getProxyStatus, startProxy, stopProxy, getSampleConfigs, importSampleConfig } from '../api/settings'
import { changePassword } from '../api/auth'
import type { UserSettings, ProxyStatus, SampleConfig, ConnectivityResult } from '../types'

interface ProxyNode {
  name: string
  server: string
  port: number
  type: string
}

interface ProxySettings {
  proxy_enabled: boolean
  proxy_url: string
  proxy_config_path: string | null
  proxy_embedded_port: string | null
  nodes: ProxyNode[]
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<UserSettings>({ refresh_interval: '30' })
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(false)

  // proxy
  const [proxy, setProxy] = useState<ProxySettings>({
    proxy_enabled: false,
    proxy_url: '',
    proxy_config_path: null,
    proxy_embedded_port: null,
    nodes: [],
  })
  const [proxySaving, setProxySaving] = useState(false)
  const [proxySaved, setProxySaved] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<ConnectivityResult | null>(null)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<{ ok: boolean; message: string } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [sampleConfigs, setSampleConfigs] = useState<SampleConfig[]>([])
  const [showAdvanced, setShowAdvanced] = useState(false)

  // embedded proxy
  const [proxyStatus, setProxyStatus] = useState<ProxyStatus | null>(null)
  const [proxyPort, setProxyPort] = useState(7890)
  const [proxyLoading, setProxyLoading] = useState(false)

  // password
  const [passwordError, setPasswordError] = useState('')
  const [passwordSuccess, setPasswordSuccess] = useState('')
  const [passwordSaving, setPasswordSaving] = useState(false)

  useEffect(() => {
    getSettings().then((res) => setSettings(res.data)).catch(() => {})
    getProxySettings().then((res) => {
      const d = res.data
      setProxy((prev) => ({
        ...prev,
        proxy_enabled: d.proxy_enabled === 'true' || d.proxy_enabled === true,
        proxy_url: d.proxy_url || '',
        proxy_config_path: d.proxy_config_path || null,
        nodes: d.nodes || prev.nodes,
      }))
    }).catch(() => {})
    getProxyStatus().then((res) => {
      setProxyStatus(res.data)
      if (res.data.port) setProxyPort(res.data.port)
    }).catch(() => {})
    getSampleConfigs().then((res) => setSampleConfigs(res.data.samples || [])).catch(() => {})
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

  const handleProxySave = async () => {
    setProxySaving(true)
    try {
      await saveProxySettings({
        proxy_enabled: proxy.proxy_enabled,
        proxy_url: proxy.proxy_url,
        proxy_embedded_port: String(proxyPort),
      })
      setProxySaved(true)
      setTimeout(() => setProxySaved(false), 2000)
    } catch {}
    setProxySaving(false)
  }

  const handleTestProxy = async () => {
    if (!proxy.proxy_url) return
    setTesting(true)
    setTestResult(null)
    try {
      const res = await testProxy(proxy.proxy_url)
      setTestResult(res.data) // now multi-target: {google, github, okx}
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setTestResult(null)
    }
    setTesting(false)
  }

  const handleImportConfig = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImporting(true)
    setImportResult(null)
    try {
      const res = await importProxyConfig(file)
      const nodes = res.data.nodes || []
      const msg = res.data.message || `成功导入 ${nodes.length} 个节点`
      setProxy((prev) => ({ ...prev, nodes }))
      setImportResult({ ok: true, message: msg })
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setImportResult({ ok: false, message: detail || '导入失败' })
    }
    setImporting(false)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleImportSample = async (path: string) => {
    setImporting(true)
    setImportResult(null)
    try {
      const res = await importSampleConfig(path)
      const nodes = res.data.nodes || []
      const msg = res.data.message || `成功导入 ${nodes.length} 个节点`
      setProxy((prev) => ({ ...prev, nodes }))
      setImportResult({ ok: true, message: msg })
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setImportResult({ ok: false, message: detail || '导入失败' })
    }
    setImporting(false)
  }

  const handleStartProxy = async () => {
    setProxyLoading(true)
    try {
      const res = await startProxy({ port: proxyPort })
      setProxyStatus(res.data)
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.response?.data?.message || '启动失败'
      setProxyStatus({ status: 'error', port: proxyPort, pid: null, started_at: null, uptime_seconds: 0 })
    }
    setProxyLoading(false)
  }

  const handleStopProxy = async () => {
    setProxyLoading(true)
    try {
      const res = await stopProxy()
      setProxyStatus(res.data)
    } catch (err: any) {
      setProxyStatus({ status: 'stopped', port: proxyPort, pid: null, started_at: null, uptime_seconds: 0 })
    }
    setProxyLoading(false)
  }

  const handlePasswordChange = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setPasswordError('')
    setPasswordSuccess('')

    const form = e.currentTarget
    const oldPassword = (form.elements.namedItem('old_password') as HTMLInputElement).value
    const newPassword = (form.elements.namedItem('new_password') as HTMLInputElement).value
    const confirmPassword = (form.elements.namedItem('confirm_password') as HTMLInputElement).value

    if (newPassword.length < 6) {
      setPasswordError('新密码至少需要6位字符')
      return
    }
    if (newPassword !== confirmPassword) {
      setPasswordError('两次输入的新密码不一致')
      return
    }

    setPasswordSaving(true)
    try {
      await changePassword({ old_password: oldPassword, new_password: newPassword })
      setPasswordSuccess('密码修改成功')
      form.reset()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setPasswordError(detail || '密码修改失败')
    }
    setPasswordSaving(false)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-[#EDF0F7]">系统设置</h2>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-panel p-5 max-w-lg"
      >
        <h3 className="text-xs text-[#7B86A2] mb-4 uppercase tracking-wide">常规设置</h3>
        <div className="space-y-4">
          <div>
            <label className="block text-sm text-[#EDF0F7] mb-2">资产自动刷新间隔（秒）</label>
            <p className="text-xs text-[#7B86A2] mb-3">仪表盘资产余额自动拉取的间隔时间，设为 0 则关闭自动刷新</p>
            <input
              type="number"
              min={0}
              max={3600}
              value={settings.refresh_interval}
              onChange={(e) => setSettings({ ...settings, refresh_interval: e.target.value })}
              className="w-32 bg-[rgba(10,15,30,0.8)] border border-[rgba(0,212,170,0.08)] rounded-lg px-4 py-2.5 text-sm text-[#EDF0F7] focus:outline-none focus:border-[#00D4AA] transition-colors"
            />
          </div>

          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={handleSave}
              disabled={loading}
              className="flex items-center gap-2 bg-[#00D4AA] text-[#050711] rounded-lg px-5 py-2.5 text-sm font-semibold hover:bg-[#00D4AA]/90 disabled:opacity-50 transition-colors"
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
        className="glass-panel p-5 max-w-lg"
      >
        <h3 className="text-xs text-[#7B86A2] mb-4 uppercase tracking-wide">代理</h3>
        <p className="text-xs text-[#6E7A94] mb-4 leading-relaxed">
          导入机场配置文件并启动代理后，软件将通过代理访问外网（OKX API 等），不影响系统其他流量。
        </p>

        <div className="space-y-4">
          {/* === 机场配置导入区 === */}
          <div>
            <label className="text-sm text-[#EDF0F7] mb-2 block">机场配置导入</label>
            <div className="flex items-center gap-2 flex-wrap">
              <input
                ref={fileInputRef}
                type="file"
                accept=".json,.yaml,.yml,.txt,.net"
                onChange={handleImportConfig}
                className="hidden"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={importing}
                className="flex items-center gap-2 border border-[rgba(0,212,170,0.08)] text-[#EDF0F7] rounded-lg px-4 py-2 text-sm font-medium hover:bg-[rgba(0,212,170,0.06)] disabled:opacity-50 transition-colors"
              >
                {importing ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> 导入中...</>
                ) : (
                  <><Upload className="w-4 h-4" /> 导入 Clash 配置</>
                )}
              </button>
              {sampleConfigs.map((sample) => (
                <button
                  key={sample.path}
                  onClick={() => handleImportSample(sample.path)}
                  disabled={importing}
                  className="flex items-center gap-2 border border-[rgba(0,212,170,0.08)] text-[#7B86A2] rounded-lg px-3 py-2 text-xs hover:bg-[rgba(0,212,170,0.06)] hover:text-[#EDF0F7] disabled:opacity-50 transition-colors"
                >
                  <Upload className="w-3.5 h-3.5" /> {sample.name}
                </button>
              ))}
            </div>
            {importResult && (
              <div className={`flex items-center gap-2 text-xs p-3 rounded-md border mt-2 ${
                importResult.ok
                  ? 'bg-[#00D4AA]/10 text-[#00D4AA] border-[#00D4AA]/20'
                  : 'bg-[#FF4060]/10 text-[#FF4060] border-[#FF4060]/20'
              }`}>
                {importResult.ok ? <CheckCircle className="w-4 h-4 shrink-0" /> : <XCircle className="w-4 h-4 shrink-0" />}
                <span className="break-all">{importResult.message}</span>
              </div>
            )}
          </div>

          {/* === 嵌入式代理控制区 === */}
          <div className="pt-2 border-t border-[rgba(0,212,170,0.05)]">
            {/* Status */}
            <div className="flex items-center gap-3 mb-3">
              <span className={`w-2.5 h-2.5 rounded-full ${proxyStatus?.status === 'running' ? 'bg-[#00D4AA] animate-pulse' : 'bg-[#505C78]'}`} />
              <span className={`text-sm font-medium ${proxyStatus?.status === 'running' ? 'text-[#00D4AA]' : 'text-[#7B86A2]'}`}>
                {proxyStatus?.status === 'running' ? '运行中' : '已停止'}
              </span>
              {proxyStatus?.status === 'running' && proxyStatus?.port && (
                <span className="text-xs text-[#505C78] font-mono">端口: {proxyStatus.port}</span>
              )}
              {proxyStatus?.status === 'running' && proxyStatus?.uptime_seconds !== undefined && (
                <span className="text-xs text-[#505C78]">
                  运行: {Math.floor(proxyStatus.uptime_seconds / 3600)}h {Math.floor((proxyStatus.uptime_seconds % 3600) / 60)}m
                </span>
              )}
            </div>

            {/* 三目标连通性指示器 */}
            {proxyStatus?.connectivity && (
              <div className="space-y-2 mb-3">
                {([
                  { key: 'google', label: 'Google', url: 'generate_204' },
                  { key: 'github', label: 'GitHub', url: '' },
                  { key: 'okx', label: 'OKX API', url: '' },
                ] as const).map((target) => {
                  const c = proxyStatus.connectivity![target.key as keyof ConnectivityResult]
                  return (
                    <div key={target.key} className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${c.ok ? 'bg-[#00D4AA]' : 'bg-[#FF4060]'}`} />
                      <span className={`text-xs ${c.ok ? 'text-[#00D4AA]' : 'text-[#FF4060]'}`}>
                        {target.label}
                      </span>
                      {c.ok ? (
                        <span className="text-xs text-[#505C78]">{c.latency_ms}ms</span>
                      ) : (
                        <span className="text-xs text-[#505C78] break-all">{c.message || '不可达'}</span>
                      )}
                    </div>
                  )
                })}
                {proxyStatus.connectivity && !proxyStatus.connectivity.google.ok && (
                  <div className="text-xs text-[#FF4060] bg-[#FF4060]/5 p-2 rounded border border-[#FF4060]/10">
                    Google 不可达：代理未真正翻墙，请检查节点是否可用
                  </div>
                )}
              </div>
            )}

            {/* Port config */}
            <div className="mb-3">
              <label className="block text-sm text-[#E8ECF4] mb-2">监听端口</label>
              <input
                type="number"
                min={1024}
                max={65535}
                value={proxyPort}
                onChange={(e) => setProxyPort(Number(e.target.value))}
                disabled={proxyStatus?.status === 'running'}
                className="w-32 bg-[rgba(10,15,30,0.8)] border border-[rgba(0,212,170,0.08)] rounded-lg px-4 py-2.5 text-sm text-[#E8ECF4] focus:outline-none focus:border-[#00D4AA] transition-colors disabled:opacity-50"
              />
              <p className="text-xs text-[#505C78] mt-1">mihomo mixed-port，默认 7890</p>
            </div>

            {/* Start/Stop button */}
            <div className="flex items-center gap-3">
              {proxyStatus?.status === 'running' ? (
                <button
                  onClick={handleStopProxy}
                  disabled={proxyLoading}
                  className="flex items-center gap-2 bg-[#FF4060]/10 text-[#FF4060] border border-[#FF4060]/20 rounded-lg px-5 py-2.5 text-sm font-semibold hover:bg-[#FF4060]/20 disabled:opacity-50 transition-colors"
                >
                  {proxyLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Square className="w-4 h-4" />}
                  {proxyLoading ? '停止中...' : '停止代理'}
                </button>
              ) : (
                <button
                  onClick={handleStartProxy}
                  disabled={proxyLoading}
                  className="flex items-center gap-2 bg-[#00D4AA] text-[#06080F] rounded-lg px-5 py-2.5 text-sm font-semibold hover:bg-[#00D4AA]/90 disabled:opacity-50 transition-colors"
                >
                  {proxyLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                  {proxyLoading ? '启动中...' : '启动代理'}
                </button>
              )}
            </div>
          </div>

          {/* === 可用节点列表 === */}
          {proxy.nodes.length > 0 && (
            <div className="pt-2 border-t border-[rgba(0,212,170,0.05)]">
              <label className="text-sm text-[#EDF0F7]">可用节点</label>
              <p className="text-xs text-[#505C78] mb-2">节点选择由配置文件中的代理组规则决定</p>
              <div className="space-y-1 max-h-40 overflow-y-auto">
                {proxy.nodes.map((node, idx) => (
                  <div
                    key={idx}
                    className="w-full text-left px-3 py-2 rounded-md text-xs bg-[rgba(10,15,30,0.8)] border border-[rgba(0,212,170,0.08)] text-[#7B86A2]"
                  >
                    <Wifi className="w-3.5 h-3.5 inline mr-2 flex-shrink-0" />
                    <span className="font-mono truncate">
                      {node.name} ({node.type}://{node.server}:{node.port})
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* === 高级：手动指定外部代理（折叠区）=== */}
          <div className="pt-2 border-t border-[rgba(0,212,170,0.05)]">
            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-2 text-xs text-[#7B86A2] hover:text-[#EDF0F7] transition-colors"
            >
              <Server className="w-3.5 h-3.5" />
              高级：手动指定外部代理
              <span className="text-[#505C78]">{showAdvanced ? '▾' : '▸'}</span>
            </button>
            {showAdvanced && (
              <div className="mt-3 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <label className="text-sm text-[#EDF0F7]">启用手动代理</label>
                    <p className="text-xs text-[#7B86A2] mt-0.5">使用外部代理软件时填写</p>
                  </div>
                  <button
                    onClick={() => {
                      if (proxyStatus?.status === 'running') return
                      setProxy((prev) => ({ ...prev, proxy_enabled: !prev.proxy_enabled }))
                    }}
                    disabled={proxyStatus?.status === 'running'}
                    className={`relative w-10 h-5 rounded-full transition-colors disabled:opacity-30 ${
                      proxy.proxy_enabled ? 'bg-[#00D4AA]' : 'bg-[rgba(0,212,170,0.08)]'
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                        proxy.proxy_enabled ? 'translate-x-5' : ''
                      }`}
                    />
                  </button>
                </div>
                {proxyStatus?.status === 'running' && (
                  <p className="text-xs text-[#FF4060]">嵌入式代理运行中，请先停止再使用手动代理</p>
                )}
                <div>
                  <label className="text-sm text-[#EDF0F7]">代理地址</label>
                  <p className="text-xs text-[#7B86A2] mt-0.5 mb-2">格式：http://127.0.0.1:7890 或 socks5://127.0.0.1:1080</p>
                  <input
                    value={proxy.proxy_url}
                    onChange={(e) => setProxy((prev) => ({ ...prev, proxy_url: e.target.value }))}
                    placeholder="http://127.0.0.1:7890"
                    disabled={proxyStatus?.status === 'running'}
                    className="w-full bg-[rgba(10,15,30,0.8)] border border-[rgba(0,212,170,0.08)] rounded-lg px-4 py-2.5 text-sm text-[#EDF0F7] font-mono focus:outline-none focus:border-[#00D4AA] transition-colors disabled:opacity-50"
                  />
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={handleTestProxy}
                    disabled={testing || !proxy.proxy_url || proxyStatus?.status === 'running'}
                    className="flex items-center gap-2 border border-[rgba(0,212,170,0.08)] text-[#EDF0F7] rounded-lg px-4 py-2 text-sm font-medium hover:bg-[rgba(0,212,170,0.06)] disabled:opacity-50 transition-colors"
                  >
                    {testing ? (
                      <><Loader2 className="w-4 h-4 animate-spin" /> 测试中...</>
                    ) : (
                      <><Wifi className="w-4 h-4" /> 测试连通性</>
                    )}
                  </button>
                </div>
                {/* 手动测试结果 - 多目标 */}
                {testResult && (
                  <div className="space-y-1 p-3 rounded-md border border-[rgba(0,212,170,0.08)] bg-[rgba(10,15,30,0.8)]">
                    {([
                      { key: 'google', label: 'Google' },
                      { key: 'github', label: 'GitHub' },
                      { key: 'okx', label: 'OKX API' },
                    ] as const).map((target) => {
                      const c = testResult[target.key as keyof ConnectivityResult]
                      return (
                        <div key={target.key} className="flex items-center gap-2">
                          <span className={`w-2 h-2 rounded-full ${c.ok ? 'bg-[#00D4AA]' : 'bg-[#FF4060]'}`} />
                          <span className={`text-xs ${c.ok ? 'text-[#00D4AA]' : 'text-[#FF4060]'}`}>
                            {target.label}
                          </span>
                          {c.ok ? (
                            <span className="text-xs text-[#505C78]">{c.latency_ms}ms</span>
                          ) : (
                            <span className="text-xs text-[#505C78] break-all">{c.message || '不可达'}</span>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* === 保存按钮 === */}
          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={handleProxySave}
              disabled={proxySaving}
              className="flex items-center gap-2 bg-[#00D4AA] text-[#050711] rounded-lg px-5 py-2.5 text-sm font-semibold hover:bg-[#00D4AA]/90 disabled:opacity-50 transition-colors"
            >
              <Save className="w-4 h-4" />
              {proxySaving ? '保存中...' : '保存代理设置'}
            </button>
            {proxySaved && (
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
        transition={{ delay: 0.15 }}
        className="glass-panel p-5 max-w-lg"
      >
        <h3 className="text-xs text-[#7B86A2] mb-4 uppercase tracking-wide">密码修改</h3>
        <form onSubmit={handlePasswordChange} className="space-y-4">
          {passwordError && (
            <div className="bg-[#FF4060]/10 text-[#FF4060] text-xs p-3 rounded-md border border-[#FF4060]/20">{passwordError}</div>
          )}
          {passwordSuccess && (
            <div className="bg-[#00D4AA]/10 text-[#00D4AA] text-xs p-3 rounded-md border border-[#00D4AA]/20">{passwordSuccess}</div>
          )}
          <div>
            <label className="block text-sm text-[#EDF0F7] mb-2">旧密码</label>
            <input name="old_password" type="password" required placeholder="输入当前密码" className="w-full bg-[rgba(10,15,30,0.8)] border border-[rgba(0,212,170,0.08)] rounded-lg px-4 py-2.5 text-sm text-[#EDF0F7] focus:outline-none focus:border-[#00D4AA] transition-colors" />
          </div>
          <div>
            <label className="block text-sm text-[#EDF0F7] mb-2">新密码</label>
            <input name="new_password" type="password" required minLength={6} placeholder="至少6位字符" className="w-full bg-[rgba(10,15,30,0.8)] border border-[rgba(0,212,170,0.08)] rounded-lg px-4 py-2.5 text-sm text-[#EDF0F7] focus:outline-none focus:border-[#00D4AA] transition-colors" />
          </div>
          <div>
            <label className="block text-sm text-[#EDF0F7] mb-2">确认新密码</label>
            <input name="confirm_password" type="password" required placeholder="再次输入新密码" className="w-full bg-[rgba(10,15,30,0.8)] border border-[rgba(0,212,170,0.08)] rounded-lg px-4 py-2.5 text-sm text-[#EDF0F7] focus:outline-none focus:border-[#00D4AA] transition-colors" />
          </div>
          <button
            type="submit"
            disabled={passwordSaving}
            className="flex items-center gap-2 bg-[#00D4AA] text-[#050711] rounded-lg px-5 py-2.5 text-sm font-semibold hover:bg-[#00D4AA]/90 disabled:opacity-50 transition-colors"
          >
            <Lock className="w-4 h-4" />
            {passwordSaving ? '修改中...' : '修改密码'}
          </button>
        </form>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="glass-panel p-5 max-w-lg"
      >
        <h3 className="text-xs text-[#7B86A2] mb-3 uppercase tracking-wide">说明</h3>
        <div className="text-sm text-[#7B86A2] space-y-2">
          <p>自动刷新运行在前端浏览器中，页面关闭即停止。</p>
          <p>刷新间隔过短可能触发 OKX API 频率限制，建议不低于 10 秒。</p>
          <p>代理配置用于访问 OKX API 时使用代理连接，适用于需要科学上网的环境。</p>
        </div>
      </motion.div>
    </div>
  )
}
