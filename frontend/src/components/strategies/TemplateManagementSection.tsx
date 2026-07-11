import { useRef, useState } from 'react'
import { X, Edit2, Trash2, Loader2, Download, Upload } from 'lucide-react'
import Modal from '../Modal'
import Dropdown from '../Dropdown'
import { createTemplate, exportTemplate, importTemplate } from '../../api/strategies'
import type { StrategyTemplate } from '../../types'

interface TemplateManagementSectionProps {
  showNewTemplate: boolean
  setShowNewTemplate: (v: boolean) => void
  showTemplateMgmt: boolean
  setShowTemplateMgmt: (v: boolean) => void
  templates: StrategyTemplate[]
  onCreated: () => void
  onEdit: (id: number) => void
  onDelete: (id: number) => Promise<void>
  deletingTemplateId: number | null
}

export default function TemplateManagementSection({
  showNewTemplate,
  setShowNewTemplate,
  showTemplateMgmt,
  setShowTemplateMgmt,
  templates,
  onCreated,
  onEdit,
  onDelete,
  deletingTemplateId,
}: TemplateManagementSectionProps) {
  return (
    <>
      <NewTemplateModal
        open={showNewTemplate}
        onClose={() => setShowNewTemplate(false)}
        onCreated={onCreated}
      />
      <TemplateMgmtModal
        open={showTemplateMgmt}
        onClose={() => setShowTemplateMgmt(false)}
        templates={templates}
        onEdit={onEdit}
        onDelete={onDelete}
        deletingTemplateId={deletingTemplateId}
        onRefresh={onCreated}
      />
    </>
  )
}

function NewTemplateModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: () => void
}) {
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [fields, setFields] = useState<{ key: string; label: string; type: string; default: string; step: string; min: string; max: string; hint: string }[]>([])
  const [saving, setSaving] = useState(false)

  const addField = () => {
    setFields([...fields, { key: '', label: '', type: 'number', default: '0', step: '0.01', min: '', max: '', hint: '' }])
  }

  const removeField = (idx: number) => {
    setFields(fields.filter((_, i) => i !== idx))
  }

  const updateField = (idx: number, prop: string, value: string) => {
    setFields(fields.map((f, i) => (i === idx ? { ...f, [prop]: value } : f)))
  }

  const handleSave = async () => {
    if (!name.trim()) return
    const defaultParams: Record<string, unknown> = {}
    const paramSchema: Record<string, unknown> = {}
    for (const f of fields) {
      if (!f.key.trim()) continue
      const v = f.type === 'number' ? Number(f.default) : f.default
      defaultParams[f.key] = v
      paramSchema[f.key] = {
        label: f.label || f.key,
        type: f.type,
        default: v,
        step: f.type === 'number' ? Number(f.step) || 1 : undefined,
        min: f.min ? Number(f.min) : undefined,
        max: f.max ? Number(f.max) : undefined,
        hint: f.hint || undefined,
      }
    }

    setSaving(true)
    try {
      await createTemplate({
        name: name.trim(),
        strategy_type: name.trim().toLowerCase().replace(/\s+/g, '_'),
        description: desc || undefined,
        default_params: defaultParams,
        param_schema: paramSchema,
      })
      setName('')
      setDesc('')
      setFields([])
      onClose()
      onCreated()
    } catch { /* ignore */ }
    finally { setSaving(false) }
  }

  return (
    <Modal open={open} onClose={onClose} title="创建自定义策略模板" wide scrollable={false}>
      <div className="space-y-3">
        <div>
          <label className="text-xs text-[#6B6B7B]">模板名称</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="我的自定义策略"
            className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] mt-1 focus:outline-none focus:border-[#00D4AA]"
          />
        </div>
        <div>
          <label className="text-xs text-[#6B6B7B]">策略描述</label>
          <input
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            placeholder="描述策略逻辑"
            className="w-full bg-[#0C0C14] border border-[#1E1E28] rounded-md px-3 py-2 text-sm text-[#E8E8ED] mt-1 focus:outline-none focus:border-[#00D4AA]"
          />
        </div>

        <div className="border-t border-[#1E1E28] pt-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-[#6B6B7B] uppercase tracking-wide">参数定义</span>
            <button
              onClick={addField}
              className="text-xs text-[#00D4AA] hover:underline"
            >
              + 添加参数
            </button>
          </div>

          <div className="space-y-3">
            {fields.map((f, idx) => (
              <div key={idx} className="bg-[#0C0C14] border border-[#1E1E28] rounded-lg p-3 relative">
                <button onClick={() => removeField(idx)} className="absolute top-2 right-2 text-[#6B6B7B] hover:text-[#FF4757]">
                  <X className="w-3.5 h-3.5" />
                </button>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <div className="min-w-0">
                    <label className="text-[10px] text-[#6B6B7B]">参数名</label>
                    <input
                      value={f.key}
                      onChange={(e) => updateField(idx, 'key', e.target.value)}
                      placeholder="e.g. upper_price"
                      className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
                    />
                  </div>
                  <div className="min-w-0">
                    <label className="text-[10px] text-[#6B6B7B]">显示名</label>
                    <input
                      value={f.label}
                      onChange={(e) => updateField(idx, 'label', e.target.value)}
                      placeholder="e.g. 价格上限"
                      className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
                    />
                  </div>
                  <div className="min-w-0">
                    <label className="text-[10px] text-[#6B6B7B]">类型</label>
                    <Dropdown
                      options={[{ value: 'number', label: '数字' }, { value: 'string', label: '文本' }, { value: 'select', label: '下拉' }]}
                      value={f.type}
                      onChange={(v) => updateField(idx, 'type', String(v))}
                      className="mt-0.5 w-full"
                    />
                  </div>
                  <div className="min-w-0">
                    <label className="text-[10px] text-[#6B6B7B]">默认值</label>
                    <input
                      value={f.default}
                      onChange={(e) => updateField(idx, 'default', e.target.value)}
                      className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
                    />
                  </div>
                  {f.type === 'number' && (
                    <>
                      <div className="min-w-0">
                        <label className="text-[10px] text-[#6B6B7B]">最小值</label>
                        <input
                          value={f.min}
                          onChange={(e) => updateField(idx, 'min', e.target.value)}
                          className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
                        />
                      </div>
                      <div className="min-w-0">
                        <label className="text-[10px] text-[#6B6B7B]">最大值</label>
                        <input
                          value={f.max}
                          onChange={(e) => updateField(idx, 'max', e.target.value)}
                          className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
                        />
                      </div>
                      <div className="min-w-0">
                        <label className="text-[10px] text-[#6B6B7B]">步长</label>
                        <input
                          value={f.step}
                          onChange={(e) => updateField(idx, 'step', e.target.value)}
                          className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA] font-mono"
                        />
                      </div>
                    </>
                  )}
                  <div className="min-w-0">
                    <label className="text-[10px] text-[#6B6B7B]">提示说明</label>
                    <input
                      value={f.hint}
                      onChange={(e) => updateField(idx, 'hint', e.target.value)}
                      className="w-full bg-[#14141A] border border-[#1E1E28] rounded-md px-2 py-1 text-xs text-[#E8E8ED] mt-0.5 focus:outline-none focus:border-[#00D4AA]"
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <button
          onClick={handleSave}
          disabled={saving || !name.trim()}
          className="w-full bg-[#00D4AA] text-[#0A0A0F] rounded-md py-2.5 text-sm font-semibold hover:bg-[#00D4AA]/90 disabled:opacity-50 transition-colors"
        >
          {saving ? '保存中...' : '保存自定义模板'}
        </button>
      </div>
    </Modal>
  )
}

function TemplateMgmtModal({
  open,
  onClose,
  templates,
  onEdit,
  onDelete,
  deletingTemplateId,
  onRefresh,
}: {
  open: boolean
  onClose: () => void
  templates: StrategyTemplate[]
  onEdit: (id: number) => void
  onDelete: (id: number) => Promise<void>
  deletingTemplateId: number | null
  onRefresh: () => void
}) {
  // 只展示自定义模板（过滤掉内置硬编码策略模板）
  const customTemplates = templates.filter((t) => !t.is_builtin)

  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [exportingId, setExportingId] = useState<number | null>(null)
  const [importing, setImporting] = useState(false)
  const [shareError, setShareError] = useState<string | null>(null)

  const handleExport = async (id: number) => {
    setShareError(null)
    setExportingId(id)
    try {
      await exportTemplate(id)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '导出失败'
      // axios 错误可能带后端 detail
      const detail = (e as { response?: { data?: unknown } })?.response?.data
      const detailMsg =
        detail && typeof detail === 'object' && 'detail' in detail
          ? String((detail as { detail: unknown }).detail)
          : null
      setShareError(detailMsg || msg)
    } finally {
      setExportingId(null)
    }
  }

  const handleImportClick = () => {
    setShareError(null)
    fileInputRef.current?.click()
  }

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    // 清空 input.value 以便同一文件可重复选择
    e.target.value = ''
    if (!file) return
    setShareError(null)
    setImporting(true)
    try {
      await importTemplate(file)
      onRefresh()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '导入失败'
      const detail = (e as { response?: { data?: unknown } })?.response?.data
      const detailMsg =
        detail && typeof detail === 'object' && 'detail' in detail
          ? String((detail as { detail: unknown }).detail)
          : null
      setShareError(detailMsg || msg)
    } finally {
      setImporting(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="模板管理" wide>
      {/* 顶部操作栏：导入按钮 */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-[#6B6B7B]">
          共 {customTemplates.length} 个自定义模板
        </span>
        <button
          type="button"
          onClick={handleImportClick}
          disabled={importing}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-[#00D4AA] text-[#0A0A0F] hover:bg-[#00D4AA]/90 disabled:opacity-50 transition-colors"
        >
          {importing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
          导入模板
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".json,application/json"
          className="hidden"
          onChange={handleFileChange}
        />
      </div>

      {shareError && (
        <div className="mb-3 text-xs text-[#FF4757] bg-[#FF4757]/10 border border-[#FF4757]/20 rounded-md px-3 py-2">
          {shareError}
        </div>
      )}

      <div className="space-y-2">
        {customTemplates.length === 0 ? (
          <div className="text-sm text-[#6B6B7B] text-center py-8">暂无自定义模板</div>
        ) : (
          customTemplates.map((t) => {
            const isQsModel = t.qs_model_config != null
            const hashShort = t.logic_hash ? t.logic_hash.slice(0, 8) : null
            const isDeleting = deletingTemplateId === t.id
            const isExporting = exportingId === t.id
            return (
              <div
                key={t.id}
                className="flex items-center gap-3 bg-[#0C0C14] border border-[#1E1E28] rounded-md p-3"
              >
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-[#E8E8ED] font-medium truncate">{t.name}</div>
                  <div className="text-xs text-[#6B6B7B] mt-0.5 flex items-center gap-2 flex-wrap">
                    <span className="font-mono">{t.strategy_type}</span>
                    {hashShort && (
                      <span className="font-mono text-[#6B6B7B]/70">#{hashShort}</span>
                    )}
                    {isQsModel ? (
                      <span className="text-[#00D4AA] border border-[#00D4AA]/20 rounded px-1 py-0.5 text-[10px]">QS-Model</span>
                    ) : (
                      <span className="text-[#6B6B7B] border border-[#1E1E28] rounded px-1 py-0.5 text-[10px]">参数定义</span>
                    )}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => handleExport(t.id)}
                  disabled={isExporting}
                  title="导出模板为 JSON 文件"
                  className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-md border border-[#1E1E28] text-[#E8E8ED] hover:bg-[#1A1A24] disabled:opacity-50 transition-colors shrink-0"
                >
                  {isExporting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
                  导出
                </button>
                <button
                  type="button"
                  onClick={() => onEdit(t.id)}
                  disabled={!isQsModel}
                  title={isQsModel ? '编辑模板' : '非 QS-Model 模板不支持编辑'}
                  className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-md border border-[#1E1E28] text-[#E8E8ED] hover:bg-[#1A1A24] disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
                >
                  <Edit2 className="w-3.5 h-3.5" /> 编辑
                </button>
                <button
                  type="button"
                  onClick={() => onDelete(t.id)}
                  disabled={isDeleting}
                  title="删除模板"
                  className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-md border border-[#1E1E28] text-[#FF4757] hover:bg-[#FF4757]/10 disabled:opacity-50 transition-colors shrink-0"
                >
                  {isDeleting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                  删除
                </button>
              </div>
            )
          })
        )}
      </div>
    </Modal>
  )
}
