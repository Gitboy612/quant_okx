import { useRef, useState, useCallback, type ReactNode } from 'react'

export interface Column<T> {
  key: string
  header: string
  render?: (row: T) => ReactNode
  className?: string
}

interface VirtualTableProps<T> {
  columns: Column<T>[]
  data: T[]
  keyField: string
  rowHeight?: number
  height?: number
  overscan?: number
}

/**
 * Virtual scrolling table for large datasets (> 100 rows).
 * Only renders visible rows plus an overscan buffer.
 * Supports fixed (sticky) header and horizontal scroll.
 */
export default function VirtualTable<T>({
  columns,
  data,
  keyField,
  rowHeight = 40,
  height = 400,
  overscan = 5,
}: VirtualTableProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)

  const totalHeight = data.length * rowHeight
  const startIndex = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan)
  const endIndex = Math.min(
    data.length,
    startIndex + Math.ceil(height / rowHeight) + overscan * 2,
  )
  const visibleData = data.slice(startIndex, endIndex)
  const topSpacer = startIndex * rowHeight
  const bottomSpacer = Math.max(0, totalHeight - endIndex * rowHeight)

  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop)
  }, [])

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-[#7B86A2] text-sm">
        暂无数据
      </div>
    )
  }

  return (
    <div className="glass-card rounded-xl overflow-hidden">
      <div
        ref={containerRef}
        onScroll={handleScroll}
        style={{ height, overflowY: 'auto', overflowX: 'auto' }}
        className="relative"
      >
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10">
            <tr className="border-b border-[rgba(0,212,170,0.08)] bg-[rgba(10,15,30,0.95)] backdrop-blur-sm">
              {columns.map((col) => (
                <th
                  key={col.key}
                  className={`text-left py-3 px-4 text-[10px] text-[#7B86A2] font-semibold tracking-[0.12em] uppercase whitespace-nowrap ${col.className ?? ''}`}
                >
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {topSpacer > 0 && (
              <tr style={{ height: topSpacer }} aria-hidden="true">
                <td colSpan={columns.length} />
              </tr>
            )}
            {visibleData.map((row) => (
              <tr
                key={String((row as Record<string, unknown>)[keyField])}
                style={{ height: rowHeight }}
                className="border-b border-[rgba(0,212,170,0.04)] hover:bg-[rgba(0,212,170,0.04)] transition-all duration-200"
              >
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={`py-2.5 px-4 text-[#EDF0F7] whitespace-nowrap ${col.className ?? ''}`}
                  >
                    {col.render
                      ? col.render(row)
                      : String((row as Record<string, unknown>)[col.key] ?? '-')}
                  </td>
                ))}
              </tr>
            ))}
            {bottomSpacer > 0 && (
              <tr style={{ height: bottomSpacer }} aria-hidden="true">
                <td colSpan={columns.length} />
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {/* Footer summary */}
      <div className="flex items-center justify-between px-4 py-2 border-t border-[rgba(0,212,170,0.06)] text-[10px] text-[#7B86A2]">
        <span>{data.length} 条数据</span>
        <span className="hidden sm:inline">
          虚拟滚动 · 显示 {startIndex + 1}–{endIndex}
        </span>
      </div>
    </div>
  )
}
