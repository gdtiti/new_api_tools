import { useCallback, useEffect, useState } from 'react'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'
import { StatCard } from './StatCard'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table'
import { useAuth } from '../contexts/AuthContext'
import { apiFetch, createAuthHeaders } from '../lib/api'
import { useToast } from './Toast'
import { CircleAlert, Loader2, Package, RefreshCw, Ticket } from 'lucide-react'
import { cn } from '../lib/utils'

interface PlanRecord {
  id: number
  title: string
  subtitle?: string
  price_amount: number
  currency: string
  enabled: boolean
  duration_unit?: string
  duration_value?: number
  total_amount?: number
  subscriber_count: number
  active_subscriber_count: number
  usage_rate: number
}

interface ActiveSubscriptionRecord {
  id: number
  user_id: number
  username?: string
  plan_id: number
  plan_title: string
  amount_total: number
  amount_used: number
  remaining_amount: number
  status: string | number
  source?: string
  start_time: number
  end_time: number
}

interface SubscriptionAnalyticsPayload {
  supported: boolean
  reason: string
  summary?: {
    total_plans: number
    enabled_plans: number
    total_subscriptions: number
    active_subscriptions: number
    expired_or_inactive_subscriptions: number
    total_amount: number
    total_used: number
    total_remaining: number
    overall_usage_rate: number
  }
  plans?: PlanRecord[]
  active_subscriptions?: ActiveSubscriptionRecord[]
}

export function SubscriptionAnalytics() {
  const { token } = useAuth()
  const { showToast } = useToast()

  const [data, setData] = useState<SubscriptionAnalyticsPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const apiUrl = import.meta.env.VITE_API_URL || ''

  const fetchData = useCallback(async (showRefreshToast = false) => {
    setLoading(true)
    try {
      const response = await apiFetch(`${apiUrl}/api/subscription-analytics/overview`, {
        headers: createAuthHeaders(token),
      })
      const payload = await response.json()
      if (!payload.success) throw new Error(payload.message || '加载订阅分析失败')
      setData(payload.data as SubscriptionAnalyticsPayload)
      if (showRefreshToast) showToast('success', '订阅分析已刷新')
    } catch (error) {
      console.error(error)
      showToast('error', error instanceof Error ? error.message : '加载订阅分析失败')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [apiUrl, showToast, token])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const formatTimestamp = (timestamp: number) => {
    if (!timestamp) return '-'
    return new Date(timestamp * 1000).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const formatAmount = (amount: number) => (amount / 500000).toFixed(2)

  const handleRefresh = async () => {
    setRefreshing(true)
    await fetchData(true)
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">订阅套餐分析</h2>
          <p className="text-muted-foreground mt-1">统计套餐启用情况、用户订阅使用率与当前在用明细。</p>
        </div>
        <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing || loading}>
          <RefreshCw className={cn('h-4 w-4 mr-2', (refreshing || loading) && 'animate-spin')} />
          刷新
        </Button>
      </div>

      {loading ? (
        <Card>
          <CardContent className="py-20 flex justify-center">
            <Loader2 className="h-10 w-10 animate-spin text-primary" />
          </CardContent>
        </Card>
      ) : !data?.supported ? (
        <Card className="border-yellow-500/30 bg-yellow-500/5">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-yellow-600">
              <CircleAlert className="h-5 w-5" />
              当前环境不支持订阅分析
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {data?.reason || '缺少 subscription_plans / user_subscriptions 或其关键字段。'}
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
            <StatCard
              title="套餐总数"
              value={`${data.summary?.total_plans || 0}`}
              icon={Package}
              color="blue"
              className="border-l-4 border-l-blue-500"
            />
            <StatCard
              title="启用套餐"
              value={`${data.summary?.enabled_plans || 0}`}
              icon={Ticket}
              color="green"
              className="border-l-4 border-l-green-500"
            />
            <StatCard
              title="在用订阅"
              value={`${data.summary?.active_subscriptions || 0}`}
              icon={Package}
              color="purple"
              className="border-l-4 border-l-purple-500"
            />
            <StatCard
              title="整体使用率"
              value={`${((data.summary?.overall_usage_rate || 0) * 100).toFixed(1)}%`}
              icon={RefreshCw}
              color="yellow"
              className="border-l-4 border-l-yellow-500"
            />
          </div>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">套餐概览</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <div className="rounded-md border-t border-b sm:border-0">
                <Table>
                  <TableHeader className="bg-muted/50">
                    <TableRow>
                      <TableHead>套餐</TableHead>
                      <TableHead>价格</TableHead>
                      <TableHead className="text-right">订阅人数</TableHead>
                      <TableHead className="text-right">在用人数</TableHead>
                      <TableHead className="text-right">用量率</TableHead>
                      <TableHead>状态</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(data.plans || []).map((plan) => (
                      <TableRow key={plan.id}>
                        <TableCell>
                          <div className="flex flex-col">
                            <span className="font-medium">{plan.title}</span>
                            <span className="text-xs text-muted-foreground">
                              {plan.subtitle || '-'} {plan.duration_unit ? `· ${plan.duration_value || 0}${plan.duration_unit}` : ''}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell className="font-medium">
                          {plan.currency} {Number(plan.price_amount || 0).toFixed(2)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{plan.subscriber_count.toLocaleString()}</TableCell>
                        <TableCell className="text-right tabular-nums">{plan.active_subscriber_count.toLocaleString()}</TableCell>
                        <TableCell className="text-right tabular-nums">{(plan.usage_rate * 100).toFixed(1)}%</TableCell>
                        <TableCell>
                          <Badge variant={plan.enabled ? 'success' : 'secondary'}>
                            {plan.enabled ? '启用' : '停用'}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                    {(data.plans || []).length === 0 && (
                      <TableRow>
                        <TableCell colSpan={6} className="text-center py-10 text-muted-foreground">
                          未读取到套餐数据。
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">在用套餐明细</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <div className="rounded-md border-t border-b sm:border-0">
                <Table>
                  <TableHeader className="bg-muted/50">
                    <TableRow>
                      <TableHead>用户</TableHead>
                      <TableHead>套餐</TableHead>
                      <TableHead className="text-right">总额度</TableHead>
                      <TableHead className="text-right">已用额度</TableHead>
                      <TableHead className="text-right">剩余额度</TableHead>
                      <TableHead>来源</TableHead>
                      <TableHead>到期时间</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(data.active_subscriptions || []).map((item) => (
                      <TableRow key={item.id}>
                        <TableCell>
                          <div className="flex flex-col">
                            <span className="font-medium">{item.username || `#${item.user_id}`}</span>
                            <span className="text-xs text-muted-foreground">状态 {String(item.status)}</span>
                          </div>
                        </TableCell>
                        <TableCell className="font-medium">{item.plan_title}</TableCell>
                        <TableCell className="text-right font-mono">{formatAmount(item.amount_total)}</TableCell>
                        <TableCell className="text-right font-mono">{formatAmount(item.amount_used)}</TableCell>
                        <TableCell className="text-right font-mono">{formatAmount(item.remaining_amount)}</TableCell>
                        <TableCell>{item.source || '-'}</TableCell>
                        <TableCell>{formatTimestamp(item.end_time)}</TableCell>
                      </TableRow>
                    ))}
                    {(data.active_subscriptions || []).length === 0 && (
                      <TableRow>
                        <TableCell colSpan={7} className="text-center py-10 text-muted-foreground">
                          当前没有在用订阅明细。
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
