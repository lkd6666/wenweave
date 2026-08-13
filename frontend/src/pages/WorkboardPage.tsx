import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Empty, Grid, Progress, Segmented, Skeleton, Statistic, Table, Tooltip, Typography, message } from 'antd'
import type { TableColumnsType } from 'antd'
import {
  FileTextOutlined,
  PieChartOutlined,
  ReloadOutlined,
  TeamOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { ApiError } from '../api/client'
import { workboardApi } from '../api/workboard'
import type { WorkboardData, WorkboardModelRank, WorkboardPeriod, WorkboardUserRank } from '../types'

const { Title, Text } = Typography

const PERIOD_OPTIONS: Array<{ value: WorkboardPeriod; label: string }> = [
  { value: 'today', label: '今日' },
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
  { value: 'month', label: '本月' },
]

function number(value: number) {
  const absolute = Math.abs(value)
  if (absolute < 1_000) return value.toLocaleString('zh-CN')

  const divisor = absolute >= 1_000_000 ? 1_000_000 : 1_000
  const suffix = divisor === 1_000_000 ? 'M' : 'K'
  const scaled = value / divisor
  const digits = Math.abs(scaled) >= 100 ? 0 : Math.abs(scaled) >= 10 ? 1 : 2
  return `${scaled.toFixed(digits).replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1')}${suffix}`
}
const percent = (value: number | null) => (value === null ? '--' : `${value.toFixed(value % 1 === 0 ? 0 : 2)}%`)

function TokenValue({ value }: { value: number }) {
  return <span>{number(value)}</span>
}

export default function WorkboardPage() {
  const screens = Grid.useBreakpoint()
  const isCompact = !screens.md
  const [period, setPeriod] = useState<WorkboardPeriod>('30d')
  const [data, setData] = useState<WorkboardData | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async (nextPeriod: WorkboardPeriod = period) => {
    setLoading(true)
    try {
      setData(await workboardApi.get(nextPeriod))
    } catch (error) {
      message.error(error instanceof ApiError ? String(error.detail) : '加载工作看板失败')
    } finally {
      setLoading(false)
    }
  }, [period])

  useEffect(() => {
    void load(period)
  }, [load, period])

  const changePeriod = (next: string | number) => {
    if (next !== 'today' && next !== '7d' && next !== '30d' && next !== 'month') return
    setPeriod(next)
  }

  const overview = data?.overview
  const activity = data?.tweet_activity
  const maxModelCalls = Math.max(...(data?.model_ranking.map((item) => item.call_count) ?? [0]), 1)
  const cacheHitRate = overview?.cache_hit_rate ?? 0
  const totalVersions = (activity?.ai_versions ?? 0) + (activity?.manual_versions ?? 0)
  const aiVersionShare = totalVersions === 0 ? 0 : (activity!.ai_versions / totalVersions) * 100

  const modelColumns: TableColumnsType<WorkboardModelRank> = [
    {
      title: '模型',
      dataIndex: 'display_name',
      key: 'display_name',
      render: (value: string, record: WorkboardModelRank, index: number) => (
        <div className="workboard-model-cell">
          <span className="workboard-rank-name">
            <span className="workboard-rank-index">{index + 1}</span>
            <span className="workboard-rank-label">{value}</span>
          </span>
          <span className="workboard-rank-bar" aria-hidden="true">
            <span style={{ width: `${(record.call_count / maxModelCalls) * 100}%` }} />
          </span>
        </div>
      ),
    },
    { title: '调用', dataIndex: 'call_count', key: 'call_count', align: 'right', render: (value) => number(value) },
    { title: '输入', dataIndex: 'input_tokens', key: 'input_tokens', align: 'right', responsive: ['md'], render: (value) => <TokenValue value={value} /> },
    { title: '输出', dataIndex: 'output_tokens', key: 'output_tokens', align: 'right', responsive: ['lg'], render: (value) => <TokenValue value={value} /> },
    { title: '缓存读取', dataIndex: 'cache_read_tokens', key: 'cache_read_tokens', align: 'right', responsive: ['lg'], render: (value) => <TokenValue value={value} /> },
    { title: '命中率', dataIndex: 'cache_hit_rate', key: 'cache_hit_rate', align: 'right', render: (value) => percent(value) },
  ]

  const userColumns: TableColumnsType<WorkboardUserRank> = [
    {
      title: '用户',
      dataIndex: 'display_name',
      key: 'display_name',
      render: (value: string, record: WorkboardUserRank, index: number) => (
        <span className="workboard-rank-name">
          <span className={`workboard-rank-index rank-${index + 1}`}>{index + 1}</span>
          <span className="workboard-rank-label">{value}</span>
          {record.username && record.username !== value && <Text className="workboard-user-handle" type="secondary">@{record.username}</Text>}
        </span>
      ),
    },
    { title: '调用', dataIndex: 'call_count', key: 'call_count', align: 'right', render: (value) => number(value) },
    { title: '输入', dataIndex: 'input_tokens', key: 'input_tokens', align: 'right', responsive: ['md'], render: (value) => <TokenValue value={value} /> },
    { title: '输出', dataIndex: 'output_tokens', key: 'output_tokens', align: 'right', responsive: ['lg'], render: (value) => <TokenValue value={value} /> },
    { title: '命中率', dataIndex: 'cache_hit_rate', key: 'cache_hit_rate', align: 'right', render: (value) => percent(value) },
  ]

  return (
    <main className="workboard-page">
      <header className="workboard-page-header">
        <div className="workboard-page-title">
          <Title level={4}>工作看板</Title>
          <Text type="secondary">{PERIOD_OPTIONS.find((item) => item.value === period)?.label}的工作数据</Text>
        </div>
        <div className="workboard-controls">
          <Segmented<WorkboardPeriod>
            value={period}
            options={PERIOD_OPTIONS}
            onChange={changePeriod}
            size={isCompact ? 'small' : 'middle'}
          />
          <Tooltip title="刷新数据">
            <Button aria-label="刷新工作看板" icon={<ReloadOutlined />} loading={loading} onClick={() => void load()} />
          </Tooltip>
        </div>
      </header>

      {loading && !data ? (
        <Skeleton active paragraph={{ rows: 12 }} />
      ) : !data || !overview || !activity ? (
        <Empty description="暂无可展示的工作数据" />
      ) : (
        <>
          <section className="workboard-spotlight" aria-label="模型调用指标">
            <div className="workboard-spotlight-summary">
              <span className="workboard-spotlight-label">模型调用</span>
              <strong>{number(overview.model_call_count)}</strong>
              <Text>所选周期内的模型请求总量</Text>
            </div>
            <div className="workboard-spotlight-tokens">
              <div>
                <span>输入 Token</span>
                <strong>{number(overview.input_tokens)}</strong>
              </div>
              <div>
                <span>输出 Token</span>
                <strong>{number(overview.output_tokens)}</strong>
              </div>
            </div>
            <div className="workboard-spotlight-cache">
              <Progress
                type="circle"
                percent={cacheHitRate}
                size={108}
                strokeColor="#279b88"
                trailColor="#d0e6e0"
                format={() => percent(overview.cache_hit_rate)}
              />
              <span>缓存命中率</span>
            </div>
          </section>

          <section className="workboard-utility-grid" aria-label="使用补充指标">
            <div>
              <span><TeamOutlined />活跃用户</span>
              <strong>{number(overview.active_users)}</strong>
            </div>
            <div>
              <span><PieChartOutlined />缓存读取</span>
              <strong>{number(overview.cache_read_tokens)}</strong>
            </div>
            <div>
              <span><PieChartOutlined />缓存写入</span>
              <strong>{number(overview.cache_write_tokens)}</strong>
            </div>
            <div className="is-warning">
              <span><WarningOutlined />未上报用量</span>
              <strong>{number(overview.usage_unreported_calls)}</strong>
            </div>
          </section>

          <section className="workboard-data-grid">
            <Card title="模型调用排行" className="workboard-data-card">
              <Table
                size="small"
                columns={modelColumns}
                dataSource={data.model_ranking}
                rowKey="model_id"
                pagination={false}
                scroll={{ x: 'max-content' }}
                locale={{ emptyText: '当前权限下暂无模型调用' }}
              />
            </Card>
            <div className="workboard-side-stack">
              <Card title="用户调用排行" className="workboard-data-card">
                <Table
                  size="small"
                  columns={userColumns}
                  dataSource={data.user_ranking}
                  rowKey={(row) => row.user_id ?? `deleted-${row.display_name}`}
                  pagination={false}
                  scroll={{ x: 'max-content' }}
                  locale={{ emptyText: '当前权限下暂无用户调用' }}
                />
              </Card>
              <section className="workboard-tweet-section" aria-label="推文创作活动">
                <div className="workboard-section-heading">
                  <div><Title level={5}>推文创作活动</Title><Text type="secondary">全站内容与版本汇总</Text></div>
                  <FileTextOutlined />
                </div>
                <div className="workboard-tweet-grid">
                  <Statistic title="推文总数" value={activity.total_documents} formatter={(value) => number(Number(value))} />
                  <Statistic title="本期新建" value={activity.created_documents} formatter={(value) => number(Number(value))} />
                  <Statistic title="活跃创作者" value={activity.active_creators} formatter={(value) => number(Number(value))} />
                  <Statistic title="AI 版本" value={activity.ai_versions} formatter={(value) => number(Number(value))} />
                  <Statistic title="手动与恢复版本" value={activity.manual_versions} formatter={(value) => number(Number(value))} />
                </div>
                <div className="workboard-version-bar" aria-label={`AI 版本占 ${aiVersionShare.toFixed(0)}%，手动与恢复版本占 ${(100 - aiVersionShare).toFixed(0)}%`}>
                  <span style={{ width: `${aiVersionShare}%` }} />
                </div>
                <div className="workboard-version-legend"><span>AI 版本</span><span>手动与恢复版本</span></div>
              </section>
            </div>
          </section>
        </>
      )}
    </main>
  )
}
