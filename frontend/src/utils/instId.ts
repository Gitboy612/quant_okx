// 产品类型映射
export const INST_TYPE_MAP: Record<string, string> = {
  'SPOT': '现货',
  'SWAP': '永续合约',
  'FUTURES': '交割合约',
  'OPTION': '期权',
  'MARGIN': '杠杆',
}

// 常用交易对友好名称
export const INST_ID_LABEL: Record<string, string> = {
  'BTC-USDT': 'BTC/USDT',
  'ETH-USDT': 'ETH/USDT',
  'BTC-USDT-SWAP': 'BTC 永续',
  'ETH-USDT-SWAP': 'ETH 永续',
  'BTC-USD-SWAP': 'BTC 永续 (USD)',
  'ETH-USD-SWAP': 'ETH 永续 (USD)',
  'SOL-USDT': 'SOL/USDT',
  'XRP-USDT': 'XRP/USDT',
  'DOGE-USDT': 'DOGE/USDT',
  'BNB-USDT': 'BNB/USDT',
  'ADA-USDT': 'ADA/USDT',
  'AVAX-USDT': 'AVAX/USDT',
  'DOT-USDT': 'DOT/USDT',
  'LINK-USDT': 'LINK/USDT',
  'MATIC-USDT': 'MATIC/USDT',
  'SUI-USDT': 'SUI/USDT',
  'APT-USDT': 'APT/USDT',
  'ARB-USDT': 'ARB/USDT',
  'OP-USDT': 'OP/USDT',
  'PEPE-USDT': 'PEPE/USDT',
  'WIF-USDT': 'WIF/USDT',
  'BONK-USDT': 'BONK/USDT',
  'SHIB-USDT': 'SHIB/USDT',
  'LTC-USDT': 'LTC/USDT',
  'FIL-USDT': 'FIL/USDT',
  'ATOM-USDT': 'ATOM/USDT',
  'NEAR-USDT': 'NEAR/USDT',
  'TRX-USDT': 'TRX/USDT',
  'ETC-USDT': 'ETC/USDT',
  'UNI-USDT': 'UNI/USDT',
  'AAVE-USDT': 'AAVE/USDT',
  'SOL-USDT-SWAP': 'SOL 永续',
  'DOGE-USDT-SWAP': 'DOGE 永续',
  'XRP-USDT-SWAP': 'XRP 永续',
  'LTC-USDT-SWAP': 'LTC 永续',
  'SUI-USDT-SWAP': 'SUI 永续',
  'APT-USDT-SWAP': 'APT 永续',
  'ARB-USDT-SWAP': 'ARB 永续',
  'OP-USDT-SWAP': 'OP 永续',
  'PEPE-USDT-SWAP': 'PEPE 永续',
  'FIL-USDT-SWAP': 'FIL 永续',
  'ATOM-USDT-SWAP': 'ATOM 永续',
  'LINK-USDT-SWAP': 'LINK 永续',
  'NEAR-USDT-SWAP': 'NEAR 永续',
  'TRX-USDT-SWAP': 'TRX 永续',
  'ETC-USDT-SWAP': 'ETC 永续',
  'BNB-USDT-SWAP': 'BNB 永续',
  'AVAX-USDT-SWAP': 'AVAX 永续',
  'DOT-USDT-SWAP': 'DOT 永续',
  'WIF-USDT-SWAP': 'WIF 永续',
  'SHIB-USDT-SWAP': 'SHIB 永续',
  'BONK-USDT-SWAP': 'BONK 永续',
  'AAVE-USDT-SWAP': 'AAVE 永续',
  'UNI-USDT-SWAP': 'UNI 永续',
}

export function formatInstId(instId: string): string {
  return INST_ID_LABEL[instId] || instId.replace('-', '/')
}

export function isContractPair(instId: string): boolean {
  return instId.includes('-SWAP') || instId.includes('-USD-')
}

export function getInstTypeLabel(instType: string): string {
  return INST_TYPE_MAP[instType] || instType
}