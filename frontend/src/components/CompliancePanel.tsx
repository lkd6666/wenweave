import { Alert, Badge, Collapse, Spin, Tag, Typography } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, WarningOutlined } from '@ant-design/icons'
import type { ComplianceReport } from '../types'

const { Text } = Typography

interface CompliancePanelProps {
  report: ComplianceReport | null
  loading?: boolean
}

export default function CompliancePanel({ report, loading }: CompliancePanelProps) {
  if (loading) {
    return (
      <div className="compliance-panel">
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin description="正在检测合规性…" />
        </div>
      </div>
    )
  }

  if (!report) {
    return (
      <div className="compliance-panel">
        <Text type="secondary">修改 HTML 后将自动运行微信合规检测</Text>
      </div>
    )
  }

  const diagnostics = report.diagnostics ?? []
  const gzhStrict = report.gzhStrict
  const hasError = report.hasError || Boolean(gzhStrict?.hasError)
  const hasWarning = report.hasWarning || Boolean(gzhStrict?.hasWarning)
  const statusColor = hasError ? 'error' : hasWarning ? 'warning' : 'success'
  const statusText = hasError ? '存在严重错误' : hasWarning ? '存在潜在警告' : '合规检测通过'
  const StatusIcon = hasError ? CloseCircleOutlined : hasWarning ? WarningOutlined : CheckCircleOutlined
  const diagnosticLabels = { error: '严重错误', warning: '兼容性风险', info: '提示' } as const
  const diagnosticColors = { error: 'red', warning: 'orange', info: 'blue' } as const

  const items = [
    ...(gzhStrict ? [{
      key: 'gzh-strict',
      label: (
        <span>
          主题严格检查{' '}
          {gzhStrict.hasError ? <Tag color="red">{gzhStrict.errors.length} 项错误</Tag>
            : gzhStrict.hasWarning ? <Tag color="orange">{gzhStrict.warnings.length} 项警告</Tag>
              : <Tag color="green">通过</Tag>}
        </span>
      ),
      children: (
        <div className="compliance-diagnostics">
          <Text type="secondary">span leaf 包裹：{gzhStrict.leafCount} 处</Text>
          {gzhStrict.errors.map((item) => <Alert key={item} type="error" showIcon message={item} />)}
          {gzhStrict.warnings.map((item) => <Alert key={item} type="warning" showIcon message={item} />)}
          {!gzhStrict.errors.length && !gzhStrict.warnings.length && <Text type="secondary">主题产物满足严格公众号规则</Text>}
        </div>
      ),
    }] : []),
    {
      key: 'diagnostics',
      label: (
        <span>
          详细诊断{' '}
          {diagnostics.length > 0 ? <Badge count={diagnostics.length} size="small" /> : <Tag color="green">通过</Tag>}
        </span>
      ),
      children: diagnostics.length ? (
        <div className="compliance-diagnostics">
          {diagnostics.map((diagnostic, index) => (
            <div className="compliance-diagnostic" key={`${diagnostic.code}-${diagnostic.path}-${index}`}>
              <div>
                <Tag color={diagnosticColors[diagnostic.severity]}>{diagnosticLabels[diagnostic.severity]}</Tag>
                <Text strong>{diagnostic.code}</Text>
              </div>
              <div>{diagnostic.message}</div>
              <Text type="secondary">
                {diagnostic.path}（第 {diagnostic.line} 行，第 {diagnostic.column} 列）
              </Text>
              {diagnostic.snippet && <code className="compliance-snippet">{diagnostic.snippet}</code>}
              <Text type="secondary">后果：{diagnostic.consequence}</Text>
              <Text>建议：{diagnostic.suggestion}</Text>
            </div>
          ))}
        </div>
      ) : (
        <Text type="secondary">未发现需要处理的规则命中</Text>
      ),
    },
    {
      key: 'class',
      label: (
        <span>
          类名过滤{' '}
          {report.removedClasses.length > 0 ? (
            <Badge count={report.removedClasses.length} size="small" />
          ) : (
            <Tag color="green" style={{ marginLeft: 4 }}>
              通过
            </Tag>
          )}
        </span>
      ),
      children: report.removedClasses.length ? (
        <ul className="compliance-list">
          {report.removedClasses.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      ) : (
        <Text type="secondary">所有类名均在白名单内</Text>
      ),
    },
    {
      key: 'id',
      label: (
        <span>
          id 属性剥离{' '}
          {report.removedIdAttributes.length > 0 ? (
            <Badge count={report.removedIdAttributes.length} size="small" />
          ) : (
            <Tag color="green" style={{ marginLeft: 4 }}>
              通过
            </Tag>
          )}
        </span>
      ),
      children: report.removedIdAttributes.length ? (
        <ul className="compliance-list">
          {report.removedIdAttributes.map((id) => (
            <li key={id}>{id}</li>
          ))}
        </ul>
      ) : (
        <Text type="secondary">未检测到会被剥离的 id</Text>
      ),
    },
    {
      key: 'nesting',
      label: (
        <span>
          嵌套深度（{report.maxNestingDepth} 层）{' '}
          {report.willFlattenNesting ? (
            <Tag color="red">超限</Tag>
          ) : report.maxNestingDepth > 18 ? (
            <Tag color="orange">接近上限</Tag>
          ) : (
            <Tag color="green">安全</Tag>
          )}
        </span>
      ),
      children: (
        <Text type={report.willFlattenNesting ? 'danger' : undefined}>
          {report.willFlattenNesting
            ? '嵌套深度 >= 20 层，Word 粘贴时会触发扁平化'
            : report.maxNestingDepth > 18
              ? '建议控制在 18 层以内'
              : '嵌套深度在安全范围内'}
        </Text>
      ),
    },
    {
      key: 'svg',
      label: (
        <span>
          SVG 检测{' '}
          {report.oversizedSvgBlocks.length > 0 || report.removedSvgBrs > 0 ? (
            <Tag color="red">异常</Tag>
          ) : report.hasSvg ? (
            <Tag color="green">正常</Tag>
          ) : (
            <Tag>无 SVG</Tag>
          )}
        </span>
      ),
      children: (
        <div>
          {report.hasSvg ? (
            <>
              {report.oversizedSvgBlocks.length > 0 && (
                <Alert
                  type="error"
                  showIcon
                  title={`${report.oversizedSvgBlocks.length} 个 SVG 超过 11000 字符限制`}
                  style={{ marginBottom: 8 }}
                />
              )}
              {report.removedSvgBrs > 0 && (
                <Alert type="error" showIcon title={`SVG 内含 ${report.removedSvgBrs} 个 <br> 标签`} />
              )}
              {!report.oversizedSvgBlocks.length && !report.removedSvgBrs && (
                <Text type="secondary">SVG 长度与结构正常</Text>
              )}
            </>
          ) : (
            <Text type="secondary">文档中未包含 SVG</Text>
          )}
        </div>
      ),
    },
    {
      key: 'risk',
      label: (
        <span>
          定位样式风险提示{' '}
          {report.riskStyleHints.length > 0 ? (
            <Badge count={report.riskStyleHints.length} size="small" />
          ) : null}
        </span>
      ),
      children: report.riskStyleHints.length ? (
        <ul className="compliance-list">
          {report.riskStyleHints.slice(0, 10).map((h, i) => (
            <li key={i}>{h}</li>
          ))}
        </ul>
      ) : (
        <Text type="secondary">未检测到 position/float 等定位样式</Text>
      ),
    },
    {
      key: 'empty',
      label: (
        <span>
          疑似空节点{' '}
          {report.emptyNodeSuspects.length > 0 ? (
            <Badge count={report.emptyNodeSuspects.length} size="small" />
          ) : null}
        </span>
      ),
      children: report.emptyNodeSuspects.length ? (
        <ul className="compliance-list">
          {report.emptyNodeSuspects.slice(0, 8).map((n, i) => (
            <li key={i}>
              <code>{n}</code>
            </li>
          ))}
        </ul>
      ) : (
        <Text type="secondary">未发现明显冗余空标签</Text>
      ),
    },
  ]

  return (
    <div className="compliance-panel">
      <Alert
        type={statusColor}
        showIcon
        icon={<StatusIcon />}
        title={statusText}
        style={{ marginBottom: 12 }}
      />
      <Collapse size="small" defaultActiveKey={report.hasError ? ['diagnostics', 'class', 'id', 'nesting', 'svg'] : []} items={items} />
    </div>
  )
}
