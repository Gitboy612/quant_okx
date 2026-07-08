import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { login } from '../api/auth'
import { useAuth } from '../hooks/useAuth'
import qstudioLogoSrc from '../assets/qstudio-logo.jpg'

export default function LoginPage() {
  const navigate = useNavigate()
  const auth = useAuth()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

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
    <div className="min-h-screen flex items-center justify-center relative scan-line">
      {/* Ambient glow */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full bg-[#00D4AA]/[0.03] blur-[100px] pointer-events-none" />
      <div className="absolute bottom-0 left-1/3 w-[400px] h-[400px] rounded-full bg-[#3A8BFF]/[0.02] blur-[80px] pointer-events-none" />

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.8 }}
        className="w-full max-w-sm relative z-10"
      >
        {/* Logo area */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2, duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
          className="text-center mb-10"
        >
          <motion.div
            initial={{ scale: 0, rotate: -180 }}
            animate={{ scale: 1, rotate: 0 }}
            transition={{ delay: 0.4, type: 'spring', stiffness: 150, damping: 12 }}
            className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-[#00D4AA]/20 to-[#00D4AA]/5 border border-[#00D4AA]/20 mb-5 animate-float"
          >
            <img src={qstudioLogoSrc} alt="Q-Studio" className="w-12 h-12" />
          </motion.div>
          <motion.h1
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.6, duration: 0.5 }}
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
            animate={{ opacity: 1 }}
            transition={{ delay: 0.8 }}
            className="text-sm text-[#7B86A2] mt-2 tracking-wide"
          >
            量化交易管理系统
          </motion.p>
        </motion.div>

        {/* Login form */}
        <motion.div
          initial={{ opacity: 0, y: 30, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ delay: 0.5, duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
          className="glass-panel p-8"
        >
          <form onSubmit={handleSubmit} className="space-y-5">
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.7 }}
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
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.8 }}
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
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.9 }}
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
          animate={{ opacity: 1 }}
          transition={{ delay: 1.2 }}
          className="text-center text-[10px] text-[#505C78] mt-8"
        >
          Powered by OKX API · AES-256 Encrypted
        </motion.p>
      </motion.div>
    </div>
  )
}
