interface StatusBadgeProps {
  status: string
}

const statusConfig: Record<string, { label: string; dotColor: string; textColor: string; bgColor: string; glow: boolean }> = {
  running: { label: '运行中', dotColor: 'bg-[#00D4AA]', textColor: 'text-[#00D4AA]', bgColor: 'bg-[#00D4AA]/10', glow: true },
  paused: { label: '已暂停', dotColor: 'bg-[#F0A500]', textColor: 'text-[#F0A500]', bgColor: 'bg-[#F0A500]/10', glow: false },
  stopped: { label: '已停止', dotColor: 'bg-[#505C78]', textColor: 'text-[#7B86A2]', bgColor: 'bg-[#505C78]/10', glow: false },
  error: { label: '异常', dotColor: 'bg-[#FF4060]', textColor: 'text-[#FF4060]', bgColor: 'bg-[#FF4060]/10', glow: true },
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  const config = statusConfig[status] ?? { label: status, dotColor: 'bg-[#505C78]', textColor: 'text-[#7B86A2]', bgColor: 'bg-[#505C78]/10', glow: false }

  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full ${config.bgColor} border border-[rgba(0,212,170,0.08)]`}>
      <span
        className={`inline-block w-1.5 h-1.5 rounded-full ${config.dotColor} ${
          config.glow ? 'animate-pulse shadow-[0_0_6px_currentColor]' : ''
        }`}
      />
      <span className={`text-[11px] font-medium ${config.textColor}`}>{config.label}</span>
    </span>
  )
}
