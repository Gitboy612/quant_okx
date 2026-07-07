interface StatusBadgeProps {
  status: string
}

const statusConfig: Record<string, { label: string; color: string; pulse: boolean }> = {
  running: { label: '运行中', color: 'bg-[#00D4AA]', pulse: true },
  paused: { label: '已暂停', color: 'bg-[#F0A500]', pulse: false },
  stopped: { label: '已停止', color: 'bg-[#6B6B7B]', pulse: false },
  error: { label: '异常', color: 'bg-[#FF4757]', pulse: true },
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  const config = statusConfig[status] ?? { label: status, color: 'bg-[#6B6B7B]', pulse: false }

  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`inline-block w-2 h-2 rounded-full ${config.color} ${
          config.pulse ? 'animate-pulse-glow' : ''
        }`}
      />
      <span className="text-xs text-[#6B6B7B]">{config.label}</span>
    </span>
  )
}
