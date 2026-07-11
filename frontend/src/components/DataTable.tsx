import { useState, type ReactNode } from 'react'

interface Column<T> {
  key: string
  header: string
  render?: (row: T) => ReactNode
  className?: string
}

interface DataTableProps<T> {
  columns: Column<T>[]
  data: T[]
  keyField: string
  pageSize?: number
}

/** Compute a compact list of page numbers with ellipsis for mobile-friendliness. */
function getPageNumbers(current: number, total: number): (number | '…')[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  const pages: (number | '…')[] = [1]
  if (current > 3) pages.push('…')
  const start = Math.max(2, current - 1)
  const end = Math.min(total - 1, current + 1)
  for (let i = start; i <= end; i++) pages.push(i)
  if (current < total - 2) pages.push('…')
  pages.push(total)
  return pages
}

export default function DataTable<T>({
  columns,
  data,
  keyField,
  pageSize,
}: DataTableProps<T>) {
  const [currentPage, setCurrentPage] = useState(1)

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-[#7B86A2] text-sm">
        暂无数据
      </div>
    )
  }

  const totalPages = pageSize ? Math.ceil(data.length / pageSize) : 1
  const safePage = Math.min(Math.max(1, currentPage), totalPages)
  const pagedData = pageSize
    ? data.slice((safePage - 1) * pageSize, safePage * pageSize)
    : data

  return (
    <div className="overflow-x-auto glass-card rounded-xl">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[rgba(0,212,170,0.08)]">
            {columns.map((col) => (
              <th
                key={col.key}
                className={`text-left py-3 px-4 text-[10px] text-[#7B86A2] font-semibold tracking-[0.12em] uppercase ${col.className ?? ''}`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {pagedData.map((row) => (
            <tr key={String((row as Record<string, unknown>)[keyField])} className="border-b border-[rgba(0,212,170,0.04)] hover:bg-[rgba(0,212,170,0.04)] transition-all duration-200 hover:shadow-[inset_0_0_30px_rgba(0,212,170,0.02)]">
              {columns.map((col) => (
                <td key={col.key} className={`py-3 px-4 text-[#EDF0F7] ${col.className ?? ''}`}>
                  {col.render ? col.render(row) : String((row as Record<string, unknown>)[col.key] ?? '-')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      {pageSize && totalPages > 1 && (
        <div className="flex items-center justify-between px-4 py-2.5 border-t border-[rgba(0,212,170,0.06)] gap-2">
          <span className="text-[10px] text-[#7B86A2] hidden sm:inline">
            共 {data.length} 条 · 第 {safePage}/{totalPages} 页
          </span>
          <span className="text-[10px] text-[#7B86A2] sm:hidden">
            {safePage}/{totalPages}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={safePage === 1}
              className="px-2 py-1 text-[10px] rounded text-[#7B86A2] hover:text-[#EDF0F7] hover:bg-[rgba(0,212,170,0.06)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              上一页
            </button>
            <div className="flex items-center gap-0.5">
              {getPageNumbers(safePage, totalPages).map((p, i) =>
                p === '…' ? (
                  <span key={`ellipsis-${i}`} className="px-1.5 text-[10px] text-[#505C78]">…</span>
                ) : (
                  <button
                    key={p}
                    onClick={() => setCurrentPage(p)}
                    className={`min-w-[24px] px-1.5 py-1 text-[10px] rounded font-medium transition-colors ${
                      p === safePage
                        ? 'bg-[rgba(0,212,170,0.15)] text-[#00D4AA]'
                        : 'text-[#7B86A2] hover:text-[#EDF0F7] hover:bg-[rgba(0,212,170,0.06)]'
                    }`}
                  >
                    {p}
                  </button>
                ),
              )}
            </div>
            <button
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              disabled={safePage === totalPages}
              className="px-2 py-1 text-[10px] rounded text-[#7B86A2] hover:text-[#EDF0F7] hover:bg-[rgba(0,212,170,0.06)] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              下一页
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
