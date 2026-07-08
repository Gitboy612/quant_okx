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

export default function DataTable<T>({
  columns,
  data,
  keyField,
}: DataTableProps<T>) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-[#7B86A2] text-sm">
        暂无数据
      </div>
    )
  }

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
          {data.map((row) => (
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
    </div>
  )
}
