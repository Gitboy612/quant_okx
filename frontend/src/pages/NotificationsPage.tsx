import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import {
  Plus,
  Pencil,
  Trash2,
  Mail,
  Webhook,
  Send,
  Check,
  X,
  Bell,
  Zap,
} from 'lucide-react'
import {
  getRules,
  createRule,
  updateRule,
  deleteRule,
  testNotification,
  type NotificationRule,
  type ChannelType,
  type NotificationRuleInput,
} from '../api/notifications'
import Modal from '../components/Modal'
import Dropdown from '../components/Dropdown'
import { TableSkeleton } from '../components/Skeleton'

// 事件类型可选项（与 base_strategy.py 中事件类型对齐）
const EVENT_TYPE_OPTIONS = [
  { value: 'started', label: '策略启动' },
  { value: 'stopped', label: '策略停止' },
  { value: 'paused', label: '策略暂停' },
  { value: 'resumed', label: '策略恢复' },
  { value: 'order_placed', label: '订单提交' },
  { value: 'order_filled', label: '订单成交' },
  { value: 'order_canceled', label: '订单撤销' },
  { value: 'order_failed', label: '下单失败' },
  { value: 'pnl_recorded', label: '盈亏记录' },
  { value: 'error', label: '策略错误' },
  { value: '*', label: '全部事件 (*)' },
]

const CHANNEL_OPTIONS = [
  { value: 'email', label: '邮件 (Email)' },
  { value: 'webhook', label: 'Webhook' },
  { value: 'telegram', label: 'Telegram' },
]

const CHANNEL_ICON: Record<ChannelType, typeof Mail> = {
  email: Mail,
  webhook: Webhook,
  telegram: Send,
}

const CHANNEL_COLOR: Record<ChannelType, string> = {
  email: '#4A90D9',
  webhook: '#A855F7',
  telegram: '#00D4AA',
}

const EMPTY_FORM: NotificationRuleInput = {
  name: '',
  event_types: [],
  channel_type: 'email',
  channel_config: {},
  is_active: true,
}

export default function NotificationsPage() {
  const [rules, setRules] = useState<NotificationRule[]>([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState<NotificationRuleInput>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [testingId, setTestingId] = useState<number | null>(null)

  const loadRules = () => {
    setLoading(true)
    getRules()
      .then((res) => setRules(res.data.items || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadRules()
  }, [])

  const openCreate = () => {
    setForm(EMPTY_FORM)
    setEditingId(null)
    setError('')
    setShowModal(true)
  }

  const openEdit = (rule: NotificationRule) => {
    setForm({
      name: rule.name,
      event_types: rule.event_types || [],
      channel_type: rule.channel_type,
      channel_config: rule.channel_config || {},
      is_active: rule.is_active,
    })
    setEditingId(rule.id)
    setError('')
    setShowModal(true)
  }

  const toggleEventType = (type: string) => {
    setForm((f) => {
      const has = f.event_types.includes(type)
      let next = has ? f.event_types.filter((t) => t !== type) : [...f.event_types, type]
      // 选择 * 后清除其他
      if (!has && type === '*') next = ['*']
      // 选择其他时清除 *
      if (!has && type !== '*' && next.includes('*')) next = next.filter((t) => t !== '*')
      return { ...f, event_types: next }
    })
  }

  const updateChannelConfig = (key: string, value: string) => {
    setForm((f) => ({
      ...f,
      channel_config: { ...f.channel_config, [key]: value },
    }))
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.name.trim()) {
      setError('规则名称不能为空')
      return
    }
    if (!form.event_types.length) {
      setError('至少选择一个事件类型')
      return
    }
    setSaving(true)
    setError('')
    try {
      if (editingId !== null) {
        await updateRule(editingId, form)
      } else {
        await createRule(form)
      }
      setShowModal(false)
      loadRules()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: number) => {
    if (!window.confirm('确认删除此通知规则？')) return
    try {
      await deleteRule(id)
      loadRules()
    } catch {}
  }

  const handleTest = async (rule: NotificationRule) => {
    setTestingId(rule.id)
    try {
      const res = await testNotification({
        channel_type: rule.channel_type,
        channel_config: rule.channel_config,
      })
      if (res.data.ok) {
        alert(`${rule.channel_type} 渠道测试成功`)
      } else {
        alert(`${rule.channel_type} 渠道测试失败，请检查配置`)
      }
    } catch (err: unknown) {
      alert('测试请求失败')
    } finally {
      setTestingId(null)
    }
  }

  const formatTime = (ts: string | null) =>
    ts ? new Date(ts).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '-'

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-[#EDF0F7]">告警通知</h2>
        <button
          onClick={openCreate}
          className="flex items-center gap-2 bg-[#00D4AA] text-[#050711] rounded-lg px-4 py-2 text-sm font-semibold hover:bg-[#00D4AA]/90 transition-colors"
        >
          <Plus className="w-4 h-4" /> 新建规则
        </button>
      </div>

      <div className="space-y-2">
        {loading ? (
          <div className="glass-card p-6">
            <TableSkeleton rows={3} cols={4} />
          </div>
        ) : rules.length === 0 ? (
          <div className="glass-card p-12 text-center text-[#7B86A2] text-sm flex flex-col items-center gap-2">
            <Bell className="w-10 h-10 opacity-30" />
            <span>暂无通知规则，点击上方按钮创建</span>
            <span className="text-xs text-[#505C78]">支持邮件 / Webhook / Telegram 三种渠道</span>
          </div>
        ) : (
          rules.map((rule, i) => {
            const Icon = CHANNEL_ICON[rule.channel_type]
            const color = CHANNEL_COLOR[rule.channel_type]
            return (
              <motion.div
                key={rule.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                className="glass-card p-4 flex items-start gap-4"
              >
                <div
                  className="flex items-center justify-center w-10 h-10 rounded-xl flex-shrink-0"
                  style={{ backgroundColor: `${color}15`, border: `1px solid ${color}30` }}
                >
                  <Icon className="w-5 h-5" style={{ color }} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-[#EDF0F7]">{rule.name}</span>
                    <span
                      className="text-xs px-2 py-0.5 rounded-full"
                      style={{ color, backgroundColor: `${color}15` }}
                    >
                      {rule.channel_type}
                    </span>
                    {rule.is_active ? (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-[#00D4AA]/10 text-[#00D4AA] flex items-center gap-1">
                        <Check className="w-3 h-3" /> 启用
                      </span>
                    ) : (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-[#7B86A2]/10 text-[#7B86A2] flex items-center gap-1">
                        <X className="w-3 h-3" /> 停用
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                    {(rule.event_types || []).map((t) => (
                      <span
                        key={t}
                        className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[rgba(0,212,170,0.06)] text-[#7B86A2] border border-[rgba(0,212,170,0.08)]"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                  <div className="text-[10px] text-[#505C78] mt-2">
                    创建: {formatTime(rule.created_at)} · 更新: {formatTime(rule.updated_at)}
                  </div>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  <button
                    onClick={() => handleTest(rule)}
                    disabled={testingId === rule.id}
                    title="测试发送"
                    className="p-2 rounded-md hover:bg-[rgba(0,212,170,0.06)] text-[#7B86A2] hover:text-[#00D4AA] transition-colors disabled:opacity-50"
                  >
                    <Zap className={`w-4 h-4 ${testingId === rule.id ? 'animate-pulse' : ''}`} />
                  </button>
                  <button
                    onClick={() => openEdit(rule)}
                    title="编辑"
                    className="p-2 rounded-md hover:bg-[rgba(0,212,170,0.06)] text-[#7B86A2] hover:text-[#EDF0F7] transition-colors"
                  >
                    <Pencil className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => handleDelete(rule.id)}
                    title="删除"
                    className="p-2 rounded-md hover:bg-[#FF4060]/10 text-[#7B86A2] hover:text-[#FF4060] transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </motion.div>
            )
          })
        )}
      </div>

      <Modal open={showModal} onClose={() => setShowModal(false)} title={editingId !== null ? '编辑通知规则' : '新建通知规则'} wide>
        <form onSubmit={handleSave} className="space-y-4">
          {error && (
            <div className="bg-[#FF4060]/10 text-[#FF4060] text-xs p-3 rounded-md border border-[#FF4060]/20">{error}</div>
          )}

          <div>
            <label className="text-xs text-[#7B86A2]">规则名称</label>
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
              placeholder="如：下单失败邮件告警"
              className="w-full bg-[rgba(10,15,30,0.8)] border border-[rgba(0,212,170,0.08)] rounded-md px-3 py-2 text-sm text-[#EDF0F7] mt-1 focus:outline-none focus:border-[#00D4AA]"
            />
          </div>

          <div>
            <label className="text-xs text-[#7B86A2] block mb-2">事件类型（多选）</label>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {EVENT_TYPE_OPTIONS.map((opt) => {
                const active = form.event_types.includes(opt.value)
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => toggleEventType(opt.value)}
                    className={`flex items-center gap-2 px-3 py-2 rounded-md text-xs border transition-all ${
                      active
                        ? 'bg-[#00D4AA]/10 border-[#00D4AA]/40 text-[#00D4AA]'
                        : 'bg-[rgba(10,15,30,0.8)] border-[rgba(0,212,170,0.08)] text-[#7B86A2] hover:border-[rgba(0,212,170,0.2)]'
                    }`}
                  >
                    <span
                      className={`w-3 h-3 rounded-full border flex items-center justify-center ${
                        active ? 'bg-[#00D4AA] border-[#00D4AA]' : 'border-[#505C78]'
                      }`}
                    >
                      {active && <Check className="w-2 h-2 text-[#050711]" />}
                    </span>
                    {opt.label}
                  </button>
                )
              })}
            </div>
          </div>

          <div>
            <label className="text-xs text-[#7B86A2]">通知渠道</label>
            <Dropdown
              options={CHANNEL_OPTIONS}
              value={form.channel_type}
              onChange={(v) => setForm({ ...form, channel_type: String(v) as ChannelType, channel_config: {} })}
              className="mt-1 w-full"
            />
          </div>

          {/* 渠道特定配置 */}
          <ChannelConfigForm channelType={form.channel_type} config={form.channel_config} onChange={updateChannelConfig} />

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
              className="w-4 h-4 accent-[#00D4AA]"
            />
            <span className="text-xs text-[#EDF0F7]">启用此规则</span>
          </label>

          <button
            type="submit"
            disabled={saving}
            className="w-full bg-[#00D4AA] text-[#050711] rounded-md py-2.5 text-sm font-semibold hover:bg-[#00D4AA]/90 disabled:opacity-50 transition-colors"
          >
            {saving ? '保存中...' : editingId !== null ? '保存修改' : '创建规则'}
          </button>
        </form>
      </Modal>
    </motion.div>
  )
}

// ---------------------------------------------------------------------------
// 渠道配置表单（根据 channel_type 动态渲染字段）
// ---------------------------------------------------------------------------

interface ChannelConfigFormProps {
  channelType: ChannelType
  config: Record<string, unknown>
  onChange: (key: string, value: string) => void
}

function ChannelConfigForm({ channelType, config, onChange }: ChannelConfigFormProps) {
  const inputCls =
    'w-full bg-[rgba(10,15,30,0.8)] border border-[rgba(0,212,170,0.08)] rounded-md px-3 py-2 text-sm text-[#EDF0F7] mt-1 focus:outline-none focus:border-[#00D4AA] font-mono'
  const labelCls = 'text-xs text-[#7B86A2]'

  const getStr = (k: string) => String(config[k] ?? '')

  if (channelType === 'email') {
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>SMTP 服务器</label>
            <input value={getStr('smtp_host')} onChange={(e) => onChange('smtp_host', e.target.value)} placeholder="smtp.gmail.com" className={inputCls} />
          </div>
          <div>
            <label className={labelCls}>SMTP 端口</label>
            <input value={getStr('smtp_port')} onChange={(e) => onChange('smtp_port', e.target.value)} placeholder="465" className={inputCls} />
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>用户名</label>
            <input value={getStr('smtp_user')} onChange={(e) => onChange('smtp_user', e.target.value)} placeholder="user@example.com" className={inputCls} />
          </div>
          <div>
            <label className={labelCls}>密码 / 授权码</label>
            <input type="password" value={getStr('smtp_password')} onChange={(e) => onChange('smtp_password', e.target.value)} placeholder="••••••••" className={inputCls} />
          </div>
        </div>
        <div>
          <label className={labelCls}>发件人（可选，默认同用户名）</label>
          <input value={getStr('from_email')} onChange={(e) => onChange('from_email', e.target.value)} placeholder="noreply@example.com" className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>收件人（逗号分隔多个）</label>
          <input value={getStr('to_emails')} onChange={(e) => onChange('to_emails', e.target.value)} placeholder="a@x.com, b@y.com" className={inputCls} />
        </div>
      </div>
    )
  }

  if (channelType === 'webhook') {
    return (
      <div className="space-y-3">
        <div>
          <label className={labelCls}>Webhook URL</label>
          <input value={getStr('webhook_url')} onChange={(e) => onChange('webhook_url', e.target.value)} placeholder="https://example.com/hook" className={inputCls} />
        </div>
        <div>
          <label className={labelCls}>签名密钥 Secret（可选）</label>
          <input type="password" value={getStr('secret')} onChange={(e) => onChange('secret', e.target.value)} placeholder="HMAC-SHA256 签名密钥" className={inputCls} />
          <p className="text-[10px] text-[#505C78] mt-1">设置后请求头会附带 X-Signature HMAC-SHA256 签名。</p>
        </div>
      </div>
    )
  }

  // telegram
  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Bot Token</label>
        <input value={getStr('bot_token')} onChange={(e) => onChange('bot_token', e.target.value)} placeholder="123456:ABC-DEF..." className={inputCls} />
      </div>
      <div>
        <label className={labelCls}>Chat ID</label>
        <input value={getStr('chat_id')} onChange={(e) => onChange('chat_id', e.target.value)} placeholder="-1001234567890" className={inputCls} />
      </div>
    </div>
  )
}
