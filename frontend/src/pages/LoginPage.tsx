import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { login } from '../api/auth'
import { useAuth } from '../hooks/useAuth'
import { Zap } from 'lucide-react'

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
    <div className="min-h-screen flex items-center justify-center bg-[#0A0A0F]">
      <motion.div
        initial={{ opacity: 0, y: 40 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: 'easeOut' }}
        className="w-full max-w-sm"
      >
        <div className="text-center mb-8">
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ delay: 0.2, type: 'spring', stiffness: 200 }}
            className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-[#00D4AA]/10 mb-4"
          >
            <Zap className="w-6 h-6 text-[#00D4AA]" />
          </motion.div>
          <h1 className="text-2xl font-bold text-[#E8E8ED]">QuantOKX</h1>
          <p className="text-sm text-[#6B6B7B] mt-1">量化交易管理平台</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <input
              name="username"
              type="text"
              placeholder="用户名"
              autoComplete="username"
              required
              className="w-full bg-[#14141A] border border-[#1E1E28] rounded-lg px-4 py-3 text-sm text-[#E8E8ED] placeholder-[#6B6B7B] focus:outline-none focus:border-[#00D4AA] transition-colors"
            />
          </div>
          <div>
            <input
              name="password"
              type="password"
              placeholder="密码"
              autoComplete="current-password"
              required
              className="w-full bg-[#14141A] border border-[#1E1E28] rounded-lg px-4 py-3 text-sm text-[#E8E8ED] placeholder-[#6B6B7B] focus:outline-none focus:border-[#00D4AA] transition-colors"
            />
          </div>

          {error && (
            <motion.p
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              className="text-sm text-[#FF4757]"
            >
              {error}
            </motion.p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-[#00D4AA] text-[#0A0A0F] rounded-lg py-3 text-sm font-semibold hover:bg-[#00D4AA]/90 disabled:opacity-50 transition-colors"
          >
            {loading ? '登录中...' : '登录'}
          </button>
        </form>
      </motion.div>
    </div>
  )
}


