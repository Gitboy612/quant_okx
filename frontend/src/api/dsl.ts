import client from './client'
import type { BlockCatalog, ValidationResult, DryRunResult, DryRunRequest, DslConfig } from '../types/dsl'

export function getBlocks() {
  return client.get<BlockCatalog>('/dsl/blocks')
}

export function validateDsl(config: DslConfig) {
  return client.post<ValidationResult>('/dsl/validate', config)
}

export function dryRunDsl(request: DryRunRequest) {
  return client.post<DryRunResult>('/dsl/dry-run', request)
}
