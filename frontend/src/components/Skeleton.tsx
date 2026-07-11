interface SkeletonProps {
  className?: string
}

export default function Skeleton({ className = '' }: SkeletonProps) {
  return (
    <div className={`bg-gradient-to-r from-[rgba(12,18,38,0.5)] via-[rgba(0,212,170,0.04)] to-[rgba(12,18,38,0.5)] bg-[length:200%_100%] animate-[shimmer_2s_infinite] rounded ${className}`} />
  )
}

export function TableSkeleton({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="grid gap-4" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
          {Array.from({ length: cols }).map((_, j) => (
            <Skeleton key={j} className="h-4" />
          ))}
        </div>
      ))}
    </div>
  )
}

/* ===== Chart loading skeleton ===== */
export function ChartSkeleton({ height = 280 }: { height?: number }) {
  return (
    <div className="space-y-4">
      <Skeleton className="h-4 w-40" />
      <div style={{ height }} className="w-full">
        <Skeleton className="w-full h-full rounded-lg" />
      </div>
      <div className="flex justify-between gap-4">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-3 w-16" />
      </div>
    </div>
  )
}

/* ===== Card loading skeleton (KPI cards etc.) ===== */
export function CardSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="glass-card rounded-xl p-5 relative overflow-hidden">
          <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-[#00D4AA]/40 to-transparent" />
          <Skeleton className="h-3 w-20 mb-2" />
          <Skeleton className="h-7 w-32" />
        </div>
      ))}
    </div>
  )
}
