import client from './client'
import type { StrategyTemplate, StrategyInstance, FeasibilityResult, ApiCallLogItem } from '../types'
import type { QSModelConfig } from '../types/dsl'

export interface StrategyTemplateCreate {
  name: string
  strategy_type: string
  description?: string
  default_params: Record<string, unknown>
  param_schema: Record<string, unknown> | null
  dsl_config?: Record<string, unknown> | null
  qs_model_config?: QSModelConfig
  force?: boolean
}

export function listInstances() {
  return client.get<StrategyInstance[]>('/strategies/instances')
}

export function listTemplates() {
  return client.get<StrategyTemplate[]>('/strategies/templates')
}

export function checkFeasibility(id: number) {
  return client.get<FeasibilityResult>(`/strategies/instances/${id}/feasibility`)
}

export function listApiCallLogs(params: { strategy_instance_id?: number; limit?: number }) {
  return client.get<ApiCallLogItem[]>('/strategies/api-call-logs', { params })
}

export function createTemplate(data: StrategyTemplateCreate) {
  return client.post<StrategyTemplate>('/strategies/templates', data)
}

export function updateTemplate(id: number, body: Partial<StrategyTemplateCreate>) {
  return client.put<StrategyTemplate>(`/strategies/templates/${id}`, body)
}

export function deleteTemplate(id: number) {
  return client.delete(`/strategies/templates/${id}`)
}

/**
 * 导出策略模板为 JSON 文件并触发浏览器下载。
 *
 * 调用 GET /strategies/templates/{id}/export，后端返回 application/json
 * 并带 Content-Disposition: attachment。前端用 Blob + URL.createObjectURL
 * 触发下载（不经过 axios 默认的 JSON 解析）。
 *
 * 文件名优先取响应头 Content-Disposition 中的 filename*=UTF-8'' 编码值，
 * 回退到 filename="..."，再回退到 `template_{id}.json`。
 */
export async function exportTemplate(id: number): Promise<void> {
  const resp = await client.get(`/strategies/templates/${id}/export`, {
    responseType: 'blob',
  })
  // 从 Content-Disposition 解析文件名
  const cd = resp.headers['content-disposition'] as string | undefined
  let filename = `template_${id}.json`
  if (cd) {
    const starMatch = cd.match(/filename\*=UTF-8''([^;]+)/i)
    if (starMatch) {
      try {
        filename = decodeURIComponent(starMatch[1].trim())
      } catch {
        filename = starMatch[1].trim()
      }
    } else {
      const plainMatch = cd.match(/filename="?([^";]+)"?/i)
      if (plainMatch) filename = plainMatch[1].trim()
    }
  }
  const blob = new Blob([resp.data], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/**
 * 导出文件载荷类型（与后端 _build_export_payload 输出一致）。
 */
export interface TemplateExportPayload {
  export_version: string
  exported_at: string
  template: {
    name: string
    description?: string | null
    strategy_type: string
    qs_model_config: QSModelConfig
    default_params: Record<string, unknown>
    param_schema?: Record<string, unknown> | null
  }
}

/**
 * 导入策略模板。
 *
 * 读取用户选择的 JSON 文件，解析为 TemplateExportPayload，POST 到
 * /strategies/templates/import。后端会校验 QS-Model 结构、计算 logic_hash、
 * 加 "（导入）" 后缀后落库，返回新模板对象。
 *
 * @param file 用户通过 <input type="file" accept=".json"> 选择的文件
 * @returns 新创建的模板对象
 */
export async function importTemplate(file: File): Promise<StrategyTemplate> {
  const text = await file.text()
  let payload: TemplateExportPayload
  try {
    payload = JSON.parse(text) as TemplateExportPayload
  } catch (e) {
    throw new Error('文件内容不是合法的 JSON')
  }
  const resp = await client.post<StrategyTemplate>('/strategies/templates/import', payload)
  return resp.data
}

export function createInstance(data: {
  template_id: number
  account_id: number
  name: string
  symbol: string
  market_type: string
  params: Record<string, unknown>
}) {
  return client.post('/strategies/instances', data)
}

export function updateInstance(id: number, data: { name?: string; params?: Record<string, unknown> }) {
  return client.put(`/strategies/instances/${id}`, data)
}

export function deleteInstance(id: number) {
  return client.delete(`/strategies/instances/${id}`)
}

export function startInstance(id: number) {
  return client.post(`/strategies/instances/${id}/start`)
}

export function pauseInstance(id: number) {
  return client.post(`/strategies/instances/${id}/pause`)
}

export function resumeInstance(id: number) {
  return client.post(`/strategies/instances/${id}/resume`)
}

export function stopInstance(id: number) {
  return client.post(`/strategies/instances/${id}/stop`)
}
