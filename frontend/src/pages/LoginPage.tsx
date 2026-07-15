import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Lock, PieChart, Blocks, FlaskConical, Shield, Zap } from 'lucide-react'
import { login } from '../api/auth'
import { useAuth } from '../hooks/useAuth'
import qstudioLogo3dSrc from '../assets/Logo.jpg'

/* ---------- Opening Cinematic Animation ---------- */
function OpeningAnimation({ onComplete }: { onComplete: () => void }) {
  useEffect(() => {
    const t = setTimeout(onComplete, 4200)
    return () => clearTimeout(t)
  }, [onComplete])

  return (
    <motion.div
      className="fixed inset-0 z-[100] flex items-center justify-center overflow-hidden"
      style={{ background: '#050711' }}
      initial={{ opacity: 1 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.6 }}
    >
      {/* Volumetric light beams */}
      <div className="cinema-beams">
        <div className="cinema-beam cinema-beam-1" />
        <div className="cinema-beam cinema-beam-2" />
      </div>

      {/* Particle dust */}
      <div className="cinema-particles" />

      {/* Logo reveal: original blur/scale + 3D flip + light sweep, icon only (no outer frame) */}
      <div className="flex flex-col items-center relative z-10" style={{ perspective: '800px' }}>
        <motion.div
          initial={{ rotateY: -180, scale: 0.4, opacity: 0, filter: 'blur(20px) brightness(2)' }}
          animate={{ rotateY: 0, scale: 1, opacity: 1, filter: 'blur(0px) brightness(1)' }}
          transition={{ delay: 1.2, duration: 1.8, ease: [0.16, 1, 0.3, 1] }}
          className="relative"
          style={{ transformStyle: 'preserve-3d' }}
        >
          {/* Glow behind logo */}
          <div className="absolute inset-0 blur-3xl opacity-0"
            style={{
              background: 'radial-gradient(circle, rgba(0,212,170,0.35) 0%, transparent 70%)',
              animation: 'cinema-glow 2.5s ease-in-out infinite 2s',
            }}
          />
          <div
            className="relative overflow-hidden"
            style={{
              width: 72,
              height: 72,
              borderRadius: 18,
              transform: 'translateZ(20px)',
              boxShadow: '0 0 60px rgba(0,212,170,0.12), 0 0 120px rgba(0,212,170,0.04), inset 0 1px 0 rgba(255,255,255,0.05)',
            }}
          >
            <img
              src={qstudioLogo3dSrc}
              alt="Q-Studio"
              className="w-full h-full rounded-[18px]"
              style={{ filter: 'drop-shadow(0 0 8px rgba(0,212,170,0.3))' }}
            />
            {/* Light sweep overlay */}
            <div className="logo-light-sweep absolute inset-0 pointer-events-none rounded-[18px]" />
          </div>
          {/* Bottom reflection shadow */}
          <div className="absolute" style={{ width: 60, height: 10, bottom: -8, left: '50%', transform: 'translateX(-50%) rotateX(80deg)', background: 'radial-gradient(ellipse, rgba(0,212,170,0.15) 0%, transparent 70%)', filter: 'blur(4px)' }} />
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 2.8, duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
          className="mt-8 text-center"
        >
          <h1
            className="text-4xl font-bold tracking-tight"
            style={{
              background: 'linear-gradient(135deg, #00D4AA 0%, #3A8BFF 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}
          >
            Q-Studio
          </h1>
          <p className="text-xs mt-2 tracking-[0.25em] uppercase" style={{ color: '#505C78' }}>
            Quantitative Trading Platform
          </p>
        </motion.div>

        {/* Horizontal light sweep */}
        <motion.div
          className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 h-[1px]"
          style={{ background: 'linear-gradient(90deg, transparent 0%, rgba(0,212,170,0.6) 50%, transparent 100%)' }}
          initial={{ width: 0 }}
          animate={{ width: '300px' }}
          transition={{ delay: 1.5, duration: 1.2, ease: [0.16, 1, 0.3, 1] }}
        />
      </div>
    </motion.div>
  )
}

/* ---------- 3D Interactive Logo (登录界面用) ---------- */
function Logo3D() {
  const containerRef = useRef<HTMLDivElement>(null)
  const [tilt, setTilt] = useState({ x: 0, y: 0 })
  const [isHovered, setIsHovered] = useState(false)

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!containerRef.current) return
    const rect = containerRef.current.getBoundingClientRect()
    const cx = rect.left + rect.width / 2
    const cy = rect.top + rect.height / 2
    const maxAngle = 25
    const y = ((e.clientX - cx) / (rect.width / 2)) * maxAngle
    const x = ((e.clientY - cy) / (rect.height / 2)) * -maxAngle
    setTilt({ x, y })
  }, [])

  const handleMouseLeave = useCallback(() => {
    setTilt({ x: 0, y: 0 })
    setIsHovered(false)
  }, [])

  const handleMouseEnter = useCallback(() => {
    setIsHovered(true)
  }, [])

  /* 光源方向跟随鼠标 */
  const lightX = 50 + tilt.y * 1.2
  const lightY = 50 - tilt.x * 1.2

  /* 高光强度 */
  const glareIntensity = Math.min(1, (Math.abs(tilt.x) + Math.abs(tilt.y)) / 30)

  return (
    <div
      ref={containerRef}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      onMouseEnter={handleMouseEnter}
      className="inline-block cursor-pointer"
      style={{ perspective: '800px' }}
    >
      <motion.div
        initial={{ scale: 0, rotate: -180, opacity: 0 }}
        animate={{ scale: 1, rotate: 0, opacity: 1 }}
        transition={{ delay: 0.2, type: 'spring', stiffness: 120, damping: 10 }}
        className="relative inline-flex items-center justify-center"
        style={{
          width: 80,
          height: 80,
          transformStyle: 'preserve-3d',
          transform: `rotateX(${tilt.x}deg) rotateY(${tilt.y}deg)`,
          transition: 'transform 0.15s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
        }}
      >
        {/* 主 Logo 图片 */}
        <div
          className="relative"
          style={{
            width: 72,
            height: 72,
            borderRadius: 18,
            transform: 'translateZ(20px)',
            transition: 'box-shadow 0.15s ease-out, filter 0.15s ease-out',
            boxShadow: `
              ${tilt.y * 0.5}px ${-tilt.x * 0.5}px 25px rgba(0,212,170,${isHovered ? 0.2 : 0.08}),
              0 0 ${isHovered ? 50 : 30}px rgba(0,212,170,${isHovered ? 0.1 : 0.04}),
              inset 0 1px 0 rgba(255,255,255,${0.05 + glareIntensity * 0.08})
            `,
          }}
        >
          <img
            src={qstudioLogo3dSrc}
            alt="Q-Studio"
            className="w-full h-full rounded-[18px]"
            style={{
              filter: `drop-shadow(${tilt.y * 0.2}px ${-tilt.x * 0.2}px 6px rgba(0,212,170,${isHovered ? 0.4 : 0.2}))`,
              transition: 'filter 0.15s ease-out',
            }}
          />

          {/* 动态高光层 — 模拟金属反射 */}
          <div
            className="absolute inset-0 rounded-[18px] pointer-events-none"
            style={{
              background: `radial-gradient(circle at ${lightX}% ${lightY}%, rgba(255,255,255,${glareIntensity * 0.18}) 0%, transparent 55%)`,
              mixBlendMode: 'overlay',
              transition: 'background 0.15s ease-out',
            }}
          />

          {/* 边缘光泽 */}
          <div
            className="absolute inset-0 rounded-[18px] pointer-events-none"
            style={{
              border: `1px solid rgba(0,212,170,${isHovered ? 0.25 : 0.12})`,
              background: `linear-gradient(${135 + tilt.y * 2}deg, rgba(0,212,170,${glareIntensity * 0.1}) 0%, transparent 40%, transparent 60%, rgba(58,139,255,${glareIntensity * 0.06}) 100%)`,
              transition: 'all 0.15s ease-out',
            }}
          />
        </div>

        {/* 底部反射阴影 */}
        <div
          className="absolute"
          style={{
            width: 60,
            height: 10,
            bottom: -8,
            left: '50%',
            transform: `translateX(-50%) translateZ(-10px) rotateX(80deg)`,
            background: 'radial-gradient(ellipse, rgba(0,212,170,0.15) 0%, transparent 70%)',
            filter: 'blur(4px)',
            opacity: isHovered ? 1 : 0.5,
            transition: 'opacity 0.3s ease',
          }}
        />
      </motion.div>

      {/* 持续呼吸光晕 */}
      <motion.div
        className="absolute inset-0 pointer-events-none rounded-full"
        animate={{
          boxShadow: [
            '0 0 30px rgba(0,212,170,0.04)',
            '0 0 50px rgba(0,212,170,0.08)',
            '0 0 30px rgba(0,212,170,0.04)',
          ],
          scale: [1, 1.08, 1],
        }}
        transition={{
          duration: 3,
          repeat: Infinity,
          ease: 'easeInOut',
        }}
        style={{ borderRadius: '50%' }}
      />
    </div>
  )
}

/* ---------- Platform Highlights（平台差异化卖点展示） ---------- */
const platformHighlights = [
  { icon: Lock, title: '本地优先隐私', desc: 'API Key 本地加密不上传' },
  { icon: PieChart, title: '仓位隔离归因', desc: '多策略同品种独立 PnL' },
  { icon: Blocks, title: '可视化积木', desc: 'DSL 拖拽构建策略' },
  { icon: FlaskConical, title: '回测即实盘', desc: '参数一键导出实盘' },
  { icon: Shield, title: '多层风控', desc: '资金·杠杆·保证金·冲突' },
  { icon: Zap, title: '网格快速响应', desc: '事件驱动+波动快速路径' },
]

function PlatformHighlights() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.9, duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
      className="mt-8"
    >
      <div className="text-center text-[10px] text-[#505C78] uppercase tracking-[0.2em] mb-3">平台亮点</div>
      <div className="grid grid-cols-2 gap-2">
        {platformHighlights.map((h, i) => {
          const Icon = h.icon
          return (
            <motion.div
              key={h.title}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 1.0 + i * 0.06, duration: 0.4 }}
              whileHover={{
                boxShadow: '0 0 16px rgba(0, 212, 170, 0.10)',
                borderColor: 'rgba(0, 212, 170, 0.18)',
              }}
              className="glass-card rounded-lg p-2.5 flex items-start gap-2"
            >
              <div className="shrink-0 mt-0.5">
                <Icon className="w-3.5 h-3.5 text-[#00D4AA]" />
              </div>
              <div className="min-w-0">
                <div className="text-[11px] font-semibold text-[#EDF0F7] leading-tight">{h.title}</div>
                <div className="text-[9px] text-[#7B86A2] leading-tight mt-0.5">{h.desc}</div>
              </div>
            </motion.div>
          )
        })}
      </div>
    </motion.div>
  )
}

/* ---------- Login Page ---------- */
export default function LoginPage() {
  const navigate = useNavigate()
  const auth = useAuth()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showOpening, setShowOpening] = useState(true)

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    const form = new FormData(e.currentTarget)
    const username = form.get('username') as string
    const password = form.get('password') as string

    try {
      const res = await login({ username, password })
      await auth.login(res.data.access_token)
      navigate('/dashboard')
    } catch {
      setError('用户名或密码错误')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <AnimatePresence>
        {showOpening && (
          <OpeningAnimation onComplete={() => setShowOpening(false)} />
        )}
      </AnimatePresence>

      <div className="h-screen flex flex-col justify-center relative scan-line overflow-hidden">
        {/* Ambient glow */}
        <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full bg-[#00D4AA]/[0.03] blur-[100px] pointer-events-none" />
        <div className="absolute bottom-0 left-1/3 w-[400px] h-[400px] rounded-full bg-[#3A8BFF]/[0.02] blur-[80px] pointer-events-none" />

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: showOpening ? 0 : 1 }}
          transition={{ duration: 0.8, delay: 0.1 }}
          className="w-full max-w-sm relative z-10 mx-auto my-auto"
        >
          {/* Logo area — 3D 鼠标跟踪旋转 */}
          <div className="text-center mb-10">
            <div className="mb-5 flex justify-center">
              <Logo3D />
            </div>
            <motion.h1
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: showOpening ? 0 : 1, y: 0 }}
              transition={{ delay: 0.3, duration: 0.5 }}
              className="text-3xl font-bold tracking-tight flex items-center justify-center gap-2"
            >
              <span className="bg-gradient-to-r from-[#00D4AA] to-[#3A8BFF] bg-clip-text text-transparent">
                Q-Studio
              </span>
              <span className="text-[11px] font-mono font-semibold text-[#00D4AA]/50 bg-[#00D4AA]/8 border border-[#00D4AA]/15 rounded px-2 py-0.5">
                OKX
              </span>
            </motion.h1>
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: showOpening ? 0 : 1 }}
              transition={{ delay: 0.5 }}
              className="text-sm text-[#7B86A2] mt-2 tracking-wide"
            >
              量化交易管理系统
            </motion.p>
          </div>

          {/* Login form */}
          <motion.div
            initial={{ opacity: 0, y: 30, scale: 0.96 }}
            animate={{ opacity: showOpening ? 0 : 1, y: 0, scale: 1 }}
            transition={{ delay: 0.2, duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
            className="glass-panel p-8"
          >
            <form onSubmit={handleSubmit} className="space-y-5">
              <motion.div
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: showOpening ? 0 : 1, x: 0 }}
                transition={{ delay: 0.4 }}
              >
                <label className="block text-xs text-[#7B86A2] mb-2 uppercase tracking-wider">用户名</label>
                <input
                  name="username"
                  type="text"
                  placeholder="请输入用户名"
                  autoComplete="username"
                  required
                  className="w-full px-4 py-3 text-sm placeholder:text-[#505C78]"
                />
              </motion.div>

              <motion.div
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: showOpening ? 0 : 1, x: 0 }}
                transition={{ delay: 0.5 }}
              >
                <label className="block text-xs text-[#7B86A2] mb-2 uppercase tracking-wider">密码</label>
                <input
                  name="password"
                  type="password"
                  placeholder="请输入密码"
                  autoComplete="current-password"
                  required
                  className="w-full px-4 py-3 text-sm placeholder:text-[#505C78]"
                />
              </motion.div>

              {error && (
                <motion.p
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="text-sm text-[#FF4060] flex items-center gap-1.5"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-[#FF4060]" />
                  {error}
                </motion.p>
              )}

              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: showOpening ? 0 : 1, y: 0 }}
                transition={{ delay: 0.6 }}
              >
                <button
                  type="submit"
                  disabled={loading}
                  className="btn-primary w-full py-3 text-sm disabled:opacity-50"
                >
                  {loading ? (
                    <span className="flex items-center justify-center gap-2">
                      <motion.span
                        animate={{ rotate: 360 }}
                        transition={{ repeat: Infinity, duration: 1, ease: 'linear' }}
                        className="w-4 h-4 border-2 border-[#050711]/30 border-t-[#050711] rounded-full inline-block"
                      />
                      验证中...
                    </span>
                  ) : '登 录'}
                </button>
              </motion.div>
            </form>
          </motion.div>

          {/* Footer */}
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: showOpening ? 0 : 1 }}
            transition={{ delay: 0.8 }}
            className="text-center text-[10px] text-[#505C78] mt-8"
          >
            Powered by OKX API · AES-256 Encrypted
          </motion.p>

          {/* 平台亮点 — 差异化卖点展示 */}
          {!showOpening && <PlatformHighlights />}
        </motion.div>
      </div>
    </>
  )
}
