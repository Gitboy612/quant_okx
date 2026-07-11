import type { Position } from '../../types'
import { formatInstId } from '../../utils/instId'

interface PositionsSectionProps {
  positions: Position[]
}

export default function PositionsSection({ positions }: PositionsSectionProps) {
  if (positions.length === 0) return null
  return (
    <div className="mt-4 pt-4 border-t border-[rgba(0,212,170,0.06)]">
      <h4 className="text-[11px] text-[#7B86A2] uppercase tracking-[0.12em] font-semibold mb-3">当前持仓</h4>
      {/* Header row */}
      <div className="flex items-center justify-between px-3 py-1.5 text-[10px] text-[#505C78] uppercase tracking-wider">
        <span className="w-28">交易对</span>
        <span className="w-12 text-center">方向</span>
        <span className="w-20 text-right">数量</span>
        <span className="w-20 text-right">标记价</span>
        <span className="w-24 text-right">未实现盈亏</span>
      </div>
      <div className="grid grid-cols-1 gap-1.5">
        {positions.map((p, i) => (
          <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg bg-[rgba(10,15,30,0.5)] text-xs">
            <span className="font-mono text-[#EDF0F7] w-28 truncate">{formatInstId(p.instId)}</span>
            <span className={`w-12 text-center font-semibold ${p.posSide === 'long' ? 'text-[#00D4AA]' : 'text-[#FF4060]'}`}>
              {p.posSide === 'long' ? '多' : p.posSide === 'short' ? '空' : p.posSide}
            </span>
            <span className="font-mono text-[#EDF0F7] w-20 text-right">{Number(p.pos).toFixed(4)}</span>
            <span className="font-mono text-[#7B86A2] w-20 text-right">${Number(p.markPx).toFixed(2)}</span>
            <span className={`font-mono w-24 text-right font-semibold ${Number(p.upl) >= 0 ? 'text-[#00D4AA]' : 'text-[#FF4060]'}`}>
              ${Number(p.upl).toFixed(2)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
