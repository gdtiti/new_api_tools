import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, AlertTriangle, HeartPulse, Loader2, RefreshCw, Waves } from 'lucide-react'

import { useAuth } from '../contexts/AuthContext'
import { apiFetch, createAuthHeaders } from '../lib/api'
import { useToast } from './Toast'
import { Badge } from './ui/badge'
import { Button } from './ui/button'
import { Card, CardContent, CardHeader, CardTitle } from './ui/card'
import { Input } from './ui/input'
import { Select } from './ui/select'
import { StatCard } from './StatCard'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table'
import { cn } from '../lib/utils'

type WindowValue = '1h' | '6h' | '24h' | '3d' | '7d' | '14d'

interface ChannelItem {
  id: number
  name: string
  status: number
  type: number
  balance: number
  used_quota: number
  current_response_time: number
  last_test: number
  total_requests: number
  success_requests: number
  failure_requests: number
  error_rate: number
  average_response_time: number
  quota_used: number
  last_request_at: number
  estimated_peak_concurrency: number
  estimated_p95_concurrency: number
  health_score: number
  health_status: 'healthy' | 'warning' | 'critical'
}

interface TimelinePoint {
  bucket: string
  total_requests: number
  success_requests: number
  failure_requests: number
  error_rate: number
  average_response_time: number
}

interface ChannelOverviewResponse {
  supported: boolean
  summary: {
    window: string
    channel_count: number
    active_channels: number
    channels_with_traffic: number
    warning_channels: number
    critical_channels: number
    average_health_score: number
    max_estimated_peak_concurrency: number
    max_estimated_p95_concurrency: number
  }
  items: ChannelItem[]
  assumptions: string[]
}

interface ChannelDetailResponse {
  supported: boolean
  reason?: string
  channel?: ChannelItem
  timeline?: TimelinePoint[]
}

const HEALTH_VARIANT: Record<ChannelItem['health_status'], 'success' | 'secondary' | 'destructive'> = {
  healthy: 'success',
  warning: 'secondary',
  critical: 'destructive',
}

export function ChannelInsights() {
  const { token } = useAuth()
  const { showToast } = useToast()

  const [windowValue, setWindowValue] = useState<WindowValue>('24h')
  const [search, setSearch] = useState('')
  const [overview, setOverview] = useState<ChannelOverviewResponse | null>(null)
  const [selectedChannelId, setSelectedChannelId] = useState<number | null>(null)
  const [detail, setDetail] = useState<ChannelDetailResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const apiUrl = import.meta.env.VITE_API_URL || ''

  const fetchOverview = useCallback(async (showRefreshToast = false) => {
    setLoading(true)
    try {
      const response = await apiFetch(
        `${apiUrl}/api/channel-insights/overview?window=${windowValue}&limit=20`,
        { headers: createAuthHeaders(token) },
      )
      const payload = await response.json()
      if (!payload.success) throw new Error(payload.message || '加载渠道分析失败')
      const data: ChannelOverviewResponse = payload.data
      setOverview(data)
      if (data.items.length > 0) {
        setSelectedChannelId((current) => current ?? data.items[0].id)
      } else {
        setSelectedChannelId(null)
        setDetail(null)
      }
      if (showRefreshToast) showToast('success', '渠道分析已刷新')
    } catch (error) {
      console.error(error)
      showToast('error', error instanceof Error ? error.message : '加载渠道分析失败')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [apiUrl, showToast, token, windowValue])

  const fetchDetail = useCallback(async (channelId: number) => {
    setDetailLoading(true)
    try {
      const response = await apiFetch(
        `${apiUrl}/api/channel-insights/${channelId}?window=${windowValue}`,
        { headers: createAuthHeaders(token) },
      )
      const payload = await response.json()
      if (!payload.success) throw new Error(payload.message || '加载渠道明细失败')
      setDetail(payload.data as ChannelDetailResponse)
    } catch (error) {
      console.error(error)
      showToast('error', error instanceof Error ? error.message : '加载渠道明细失败')
    } finally {
      setDetailLoading(false)
    }
  }, [apiUrl, showToast, token, windowValue])

  useEffect(() => {
    fetchOverview()
  }, [fetchOverview])

  useEffect(() => {
    if (selectedChannelId != null) {
      fetchDetail(selectedChannelId)
    }
  }, [fetchDetail, selectedChannelId])

  const filteredItems = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    if (!overview?.items) return []
    if (!keyword) return overview.items
    return overview.items.filter((item) =>
      item.name.toLowerCase().includes(keyword) || String(item.id).includes(keyword),
    )
  }, [overview?.items, search])

  const formatTs = (timestamp: number) => {
    if (!timestamp) return '-'
    return new Date(timestamp * 1000).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    await fetchOverview(true)
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">渠道健康度</h2>
          <p className="text-muted-foreground mt-1">跟踪渠道健康分、失败率、响应时延与估算并发峰值。</p>
        </div>
        <div className="flex items-center gap-3">
          <Select value={windowValue} onChange={(e) => setWindowValue(e.target.value as WindowValue)}>
            <option value="1h">最近 1 小时</option>
            <option value="6h">最近 6 小时</option>
            <option value="24h">最近 24 小时</option>
            <option value="3d">最近 3 天</option>
            <option value="7d">最近 7 天</option>
            <option value="14d">最近 14 天</option>
          </Select>
          <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing || loading}>
            <RefreshCw className={cn('h-4 w-4 mr-2', (refreshing || loading) && 'animate-spin')} />
            刷新
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard
          title="观察渠道"
          value={loading ? '-' : `${overview?.summary.channel_count || 0}`}
          icon={Activity}
          color="blue"
          className="border-l-4 border-l-blue-500"
        />
        <StatCard
          title="活跃渠道"
          value={loading ? '-' : `${overview?.summary.active_channels || 0}`}
          icon={HeartPulse}
          color="green"
          className="border-l-4 border-l-green-500"
        />
        <StatCard
          title="告警渠道"
          value={loading ? '-' : `${overview?.summary.warning_channels || 0}`}
          icon={AlertTriangle}
          color="yellow"
          className="border-l-4 border-l-yellow-500"
        />
        <StatCard
          title="峰值并发估算"
          value={loading ? '-' : `${overview?.summary.max_estimated_peak_concurrency || 0}`}
          icon={Waves}
          color="purple"
          className="border-l-4 border-l-purple-500"
        />
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-medium">估算口径</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          {(overview?.assumptions || []).map((assumption) => (
            <div key={assumption} className="rounded-lg border border-dashed border-border px-3 py-2">
              {assumption}
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-[1.6fr,1fr] gap-6">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
              <CardTitle className="text-base font-medium">渠道健康列表</CardTitle>
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索渠道名称 / ID"
                className="md:w-64"
              />
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {loading ? (
              <div className="flex justify-center items-center py-20">
                <Loader2 className="h-10 w-10 animate-spin text-primary" />
              </div>
            ) : filteredItems.length === 0 ? (
              <div className="py-16 text-center text-muted-foreground">当前窗口没有可展示的渠道数据。</div>
            ) : (
              <div className="rounded-md border-t border-b sm:border-0">
                <Table>
                  <TableHeader className="bg-muted/50">
                    <TableRow>
                      <TableHead>渠道</TableHead>
                      <TableHead>健康度</TableHead>
                      <TableHead className="text-right">请求数</TableHead>
                      <TableHead className="text-right">错误率</TableHead>
                      <TableHead className="text-right">平均响应</TableHead>
                      <TableHead className="text-right">峰值并发</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredItems.map((item) => (
                      <TableRow
                        key={item.id}
                        className={cn(
                          'cursor-pointer hover:bg-muted/50',
                          selectedChannelId === item.id && 'bg-primary/5',
                        )}
                        onClick={() => setSelectedChannelId(item.id)}
                      >
                        <TableCell>
                          <div className="flex flex-col">
                            <span className="font-medium">{item.name}</span>
                            <span className="text-xs text-muted-foreground">#{item.id} · 最近测试 {formatTs(item.last_test)}</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <Badge variant={HEALTH_VARIANT[item.health_status]}>{item.health_status}</Badge>
                            <span className="text-sm font-medium">{item.health_score.toFixed(1)}</span>
                          </div>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{item.total_requests.toLocaleString()}</TableCell>
                        <TableCell className="text-right tabular-nums">{(item.error_rate * 100).toFixed(2)}%</TableCell>
                        <TableCell className="text-right tabular-nums">{item.average_response_time.toFixed(0)}ms</TableCell>
                        <TableCell className="text-right tabular-nums">{item.estimated_peak_concurrency}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-medium">渠道明细</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {detailLoading ? (
              <div className="flex justify-center items-center py-20">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
              </div>
            ) : !detail?.supported || !detail.channel ? (
              <div className="py-12 text-center text-muted-foreground">{detail?.reason || '请选择一个渠道查看明细。'}</div>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-xl border p-3">
                    <div className="text-xs text-muted-foreground">请求总数</div>
                    <div className="text-2xl font-semibold tabular-nums">{detail.channel.total_requests.toLocaleString()}</div>
                  </div>
                  <div className="rounded-xl border p-3">
                    <div className="text-xs text-muted-foreground">失败请求</div>
                    <div className="text-2xl font-semibold tabular-nums">{detail.channel.failure_requests.toLocaleString()}</div>
                  </div>
                  <div className="rounded-xl border p-3">
                    <div className="text-xs text-muted-foreground">P95 并发估算</div>
                    <div className="text-2xl font-semibold tabular-nums">{detail.channel.estimated_p95_concurrency}</div>
                  </div>
                  <div className="rounded-xl border p-3">
                    <div className="text-xs text-muted-foreground">当前响应时间</div>
                    <div className="text-2xl font-semibold tabular-nums">{detail.channel.current_response_time}ms</div>
                  </div>
                </div>

                <div className="rounded-xl border p-4 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-medium">{detail.channel.name}</div>
                    <Badge variant={HEALTH_VARIANT[detail.channel.health_status]}>
                      {detail.channel.health_status}
                    </Badge>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    余额 {detail.channel.balance.toFixed(2)} · 已用额度 {(detail.channel.used_quota / 500000).toFixed(2)} · 最近请求 {formatTs(detail.channel.last_request_at)}
                  </div>
                </div>

                <div className="space-y-2">
                  <div className="text-sm font-medium">时间线</div>
                  <div className="space-y-2 max-h-[360px] overflow-auto pr-1">
                    {(detail.timeline || []).map((point) => (
                      <div key={point.bucket} className="rounded-xl border p-3">
                        <div className="flex items-center justify-between gap-4">
                          <div className="font-medium text-sm">{point.bucket}</div>
                          <div className="text-xs text-muted-foreground">
                            错误率 {(point.error_rate * 100).toFixed(2)}% · 平均 {point.average_response_time.toFixed(0)}ms
                          </div>
                        </div>
                        <div className="mt-2 text-xs text-muted-foreground">
                          总请求 {point.total_requests.toLocaleString()} / 成功 {point.success_requests.toLocaleString()} / 失败 {point.failure_requests.toLocaleString()}
                        </div>
                      </div>
                    ))}
                    {detail.timeline?.length === 0 && (
                      <div className="text-sm text-muted-foreground">当前窗口暂无时间线样本。</div>
                    )}
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
