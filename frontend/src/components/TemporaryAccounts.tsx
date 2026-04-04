import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { CircleAlert, Loader2, RefreshCw, UserPlus, Users } from 'lucide-react'

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

interface TemporaryAccountItem {
  id: number
  user_id: number
  username: string
  default_token_id: number
  default_token_key_masked: string
  created_by: string
  remark: string
  status: 'active' | 'disabled' | 'expired' | string
  expires_at: number
  created_at: number
  updated_at: number
  is_expired: boolean
  main_user?: {
    status?: number
    quota?: number
    used_quota?: number
    group?: string
  }
  default_token?: {
    status?: number
    expired_time?: number
    remain_quota?: number
    quota?: number
  }
}

interface TemporaryAccountsPayload {
  items: TemporaryAccountItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
  summary: {
    total: number
    active: number
    disabled: number
    expired: number
  }
  capability: {
    supported: boolean
    reason: string
  }
  recent_events: Array<{
    id: number
    user_id: number
    action: string
    operator: string
    created_at: number
  }>
}

interface CreateResultPayload {
  user_id: number
  username: string
  default_token_id: number
  default_token_key: string
  default_token_key_masked: string
  expires_at: number
}

type StatusFilter = '' | 'active' | 'disabled' | 'expired'

export function TemporaryAccounts() {
  const { token } = useAuth()
  const { showToast } = useToast()

  const [data, setData] = useState<TemporaryAccountsPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('')
  const [page, setPage] = useState(1)
  const [createdCredential, setCreatedCredential] = useState<CreateResultPayload | null>(null)
  const [form, setForm] = useState({
    username: '',
    remark: '',
    expiresDays: '7',
    quotaUsd: '0',
    group_name: 'default',
    token_name: '',
  })

  const apiUrl = import.meta.env.VITE_API_URL || ''

  const fetchData = useCallback(async (showRefreshToast = false) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ page: String(page), page_size: '20' })
      if (statusFilter) params.append('status', statusFilter)
      const response = await apiFetch(`${apiUrl}/api/temporary-accounts?${params.toString()}`, {
        headers: createAuthHeaders(token),
      })
      const payload = await response.json()
      if (!payload.success) throw new Error(payload.message || '加载临时账号失败')
      setData(payload.data as TemporaryAccountsPayload)
      if (showRefreshToast) showToast('success', '临时账号数据已刷新')
    } catch (error) {
      console.error(error)
      showToast('error', error instanceof Error ? error.message : '加载临时账号失败')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [apiUrl, page, showToast, statusFilter, token])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  useEffect(() => {
    setPage(1)
  }, [statusFilter])

  const handleRefresh = async () => {
    setRefreshing(true)
    await fetchData(true)
  }

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    try {
      const expiresDays = Math.max(0, Number(form.expiresDays || '0'))
      const quotaUsd = Math.max(0, Number(form.quotaUsd || '0'))
      const expiresAt = expiresDays > 0 ? Math.floor(Date.now() / 1000 + expiresDays * 24 * 3600) : 0
      const quota = Math.round(quotaUsd * 500000)

      const response = await apiFetch(`${apiUrl}/api/temporary-accounts`, {
        method: 'POST',
        headers: createAuthHeaders(token),
        body: JSON.stringify({
          username: form.username.trim(),
          remark: form.remark,
          expires_at: expiresAt,
          quota,
          group_name: form.group_name,
          token_name: form.token_name,
        }),
      })
      const payload = await response.json()
      if (!payload.success) throw new Error(payload.message || '创建临时账号失败')

      setCreatedCredential(payload.data as CreateResultPayload)
      showToast('success', '临时账号创建成功')
      setForm({
        username: '',
        remark: '',
        expiresDays: '7',
        quotaUsd: '0',
        group_name: 'default',
        token_name: '',
      })
      await fetchData()
    } catch (error) {
      console.error(error)
      showToast('error', error instanceof Error ? error.message : '创建临时账号失败')
    } finally {
      setSubmitting(false)
    }
  }

  const toggleStatus = async (item: TemporaryAccountItem, action: 'enable' | 'disable') => {
    try {
      const response = await apiFetch(`${apiUrl}/api/temporary-accounts/${item.user_id}/${action}`, {
        method: 'POST',
        headers: createAuthHeaders(token),
        body: JSON.stringify({ reason: `temporary account ${action}` }),
      })
      const payload = await response.json()
      if (!payload.success) throw new Error(payload.message || `${action} temporary account failed`)
      showToast('success', action === 'enable' ? '账号已启用' : '账号已禁用')
      await fetchData()
    } catch (error) {
      console.error(error)
      showToast('error', error instanceof Error ? error.message : '状态更新失败')
    }
  }

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

  const filteredItems = useMemo(() => data?.items || [], [data?.items])

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">临时账号管理</h2>
          <p className="text-muted-foreground mt-1">基于主库 users/tokens + sidecar 元数据的短期账号创建与生命周期管理。</p>
        </div>
        <div className="flex items-center gap-3">
          <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}>
            <option value="">全部状态</option>
            <option value="active">仅看启用</option>
            <option value="disabled">仅看禁用</option>
            <option value="expired">仅看过期</option>
          </Select>
          <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing || loading}>
            <RefreshCw className={cn('h-4 w-4 mr-2', (refreshing || loading) && 'animate-spin')} />
            刷新
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard title="临时账号总数" value={loading ? '-' : `${data?.summary.total || 0}`} icon={Users} color="blue" className="border-l-4 border-l-blue-500" />
        <StatCard title="当前启用" value={loading ? '-' : `${data?.summary.active || 0}`} icon={UserPlus} color="green" className="border-l-4 border-l-green-500" />
        <StatCard title="已禁用" value={loading ? '-' : `${data?.summary.disabled || 0}`} icon={CircleAlert} color="yellow" className="border-l-4 border-l-yellow-500" />
        <StatCard title="已过期" value={loading ? '-' : `${data?.summary.expired || 0}`} icon={CircleAlert} color="red" className="border-l-4 border-l-red-500" />
      </div>

      {!loading && data && !data.capability.supported && (
        <Card className="border-yellow-500/30 bg-yellow-500/5">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-yellow-600">
              <CircleAlert className="h-5 w-5" />
              当前环境无法安全创建临时账号
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {data.capability.reason}
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[1.1fr,1.4fr] gap-6">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-medium">创建临时账号</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <form className="space-y-4" onSubmit={handleCreate}>
              <div className="space-y-2">
                <label className="text-sm font-medium">用户名</label>
                <Input value={form.username} onChange={(e) => setForm((current) => ({ ...current, username: e.target.value }))} placeholder="temp-user-001" required />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium">有效天数</label>
                  <Input type="number" min="0" value={form.expiresDays} onChange={(e) => setForm((current) => ({ ...current, expiresDays: e.target.value }))} />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">额度（USD）</label>
                  <Input type="number" min="0" step="0.01" value={form.quotaUsd} onChange={(e) => setForm((current) => ({ ...current, quotaUsd: e.target.value }))} />
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium">用户组</label>
                  <Input value={form.group_name} onChange={(e) => setForm((current) => ({ ...current, group_name: e.target.value }))} placeholder="default" />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">默认 Token 名称</label>
                  <Input value={form.token_name} onChange={(e) => setForm((current) => ({ ...current, token_name: e.target.value }))} placeholder="temp-token" />
                </div>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium">备注</label>
                <textarea
                  value={form.remark}
                  onChange={(e) => setForm((current) => ({ ...current, remark: e.target.value }))}
                  rows={4}
                  className="flex min-h-[96px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  placeholder="临时用途说明、回收时间、责任人等"
                />
              </div>
              <Button type="submit" disabled={submitting || !data?.capability.supported}>
                {submitting ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <UserPlus className="h-4 w-4 mr-2" />}
                创建临时账号
              </Button>
            </form>

            {createdCredential && (
              <div className="rounded-xl border border-green-500/30 bg-green-500/5 p-4 space-y-2">
                <div className="font-medium text-green-600">创建成功，请立即保存默认 Token</div>
                <div className="text-sm text-muted-foreground">用户 {createdCredential.username} / Token #{createdCredential.default_token_id}</div>
                <code className="block rounded-md bg-background px-3 py-2 text-sm font-mono break-all">
                  {createdCredential.default_token_key}
                </code>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-medium">临时账号列表</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {loading ? (
              <div className="py-20 flex justify-center">
                <Loader2 className="h-10 w-10 animate-spin text-primary" />
              </div>
            ) : filteredItems.length === 0 ? (
              <div className="py-16 text-center text-muted-foreground">暂无临时账号记录。</div>
            ) : (
              <div className="rounded-md border-t border-b sm:border-0">
                <Table>
                  <TableHeader className="bg-muted/50">
                    <TableRow>
                      <TableHead>账号</TableHead>
                      <TableHead>Token</TableHead>
                      <TableHead>状态</TableHead>
                      <TableHead>到期时间</TableHead>
                      <TableHead>备注</TableHead>
                      <TableHead className="text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredItems.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell>
                          <div className="flex flex-col">
                            <span className="font-medium">{item.username}</span>
                            <span className="text-xs text-muted-foreground">
                              user #{item.user_id} · group {item.main_user?.group || '-'}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-col">
                            <code className="text-xs font-mono bg-muted px-1.5 py-0.5 rounded w-fit">{item.default_token_key_masked || '-'}</code>
                            <span className="text-xs text-muted-foreground">token #{item.default_token_id || 0}</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant={item.status === 'active' ? 'success' : item.status === 'disabled' ? 'secondary' : 'destructive'}>
                            {item.is_expired ? 'expired' : item.status}
                          </Badge>
                        </TableCell>
                        <TableCell>{formatTimestamp(item.expires_at)}</TableCell>
                        <TableCell className="max-w-[220px] truncate" title={item.remark || ''}>{item.remark || '-'}</TableCell>
                        <TableCell className="text-right">
                          {item.status === 'disabled' || item.is_expired ? (
                            <Button variant="outline" size="sm" onClick={() => toggleStatus(item, 'enable')} disabled={item.is_expired}>
                              启用
                            </Button>
                          ) : (
                            <Button variant="outline" size="sm" onClick={() => toggleStatus(item, 'disable')}>
                              禁用
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-medium">最近操作</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {(data?.recent_events || []).map((eventItem) => (
            <div key={eventItem.id} className="rounded-xl border px-3 py-2 text-sm flex items-center justify-between gap-3">
              <div>
                <span className="font-medium">{eventItem.action}</span>
                <span className="text-muted-foreground ml-2">user #{eventItem.user_id} · {eventItem.operator || '-'}</span>
              </div>
              <span className="text-xs text-muted-foreground">{formatTimestamp(eventItem.created_at)}</span>
            </div>
          ))}
          {(data?.recent_events || []).length === 0 && (
            <div className="text-sm text-muted-foreground">暂无 sidecar 操作事件。</div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
