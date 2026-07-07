interface Column<T> {
  key: string
  header: string
  render?: (row: T) => React.ReactNode
  className?: string
}

interface DataTableProps<T> {
  columns: Column<T>[]
  data: T[]
  keyField: string
}

export default function DataTable<T extends Record<string, unknown>>({
  columns,
  data,
  keyField,
}: DataTableProps<T>) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-[#6B6B7B] text-sm">
        暂无数据
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[#1E1E28]">
            {columns.map((col) => (
              <th
                key={col.key}
                className={`text-left py-3 px-4 text-xs text-[#6B6B7B] font-medium tracking-wide uppercase ${col.className ?? ''}`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr key={String(row[keyField])} className="border-b border-[#1E1E28]/50 hover:bg-[#1A1A24]/50 transition-colors">
              {columns.map((col) => (
                <td key={col.key} className={`py-3 px-4 ${col.className ?? ''}`}>
                  {col.render ? col.render(row) : String(row[col.key] ?? '-')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
