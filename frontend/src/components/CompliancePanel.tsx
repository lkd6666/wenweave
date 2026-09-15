import { Alert, Badge, Button, Collapse, Tag, Typography } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined, SafetyCertificateOutlined, WarningOutlined } from '@ant-design/icons'
import type { ComplianceReport, ComplianceViolation } from '../types'

const { Text } = Typography

interface CompliancePanelProps {
  report: ComplianceReport | null
  loading?: boolean
  checkDisabled?: boolean
  onCheck?: () => void
}

function ViolationGroup({ violation }: { violation: ComplianceViolation }) {
  return (
    <div className="compliance-diagnostics">
      {violation.message && <Text>{violation.message}</Text>}
      {violation.items.map((item, index) => (
        <div className="compliance-diagnostic" key={`${violation.key}-${item.paragraphIndex}-${index}`}>
          <div>
            <Tag color="red">官方违规</Tag>
            <Text strong>{violation.key}</Text>
            {item.paragraphIndex !== null && item.paragraphIndex !== undefined && (
              <Text type="secondary">段落 {item.paragraphIndex}</Text>
            )}
          </div>
          {item.rules && <Text>{item.rules}</Text>}
          {item.outerHTML && <code className="compliance-snippet">{item.outerHTML}</code>}
          {Object.keys(item.measurements).length > 0 && (
            <Text type="secondary">测量数据：{JSON.stringify(item.measurements)}</Text>
          )}
        </div>
      ))}
      {!violation.items.length && <Text type="secondary">官方引擎未返回可定位节点</Text>}
    </div>
  )
}

export default function CompliancePanel({ report, loading, checkDisabled, onCheck }: CompliancePanelProps) {
  if (!report) {
    return (
      <div className="compliance-panel">
        <div className="compliance-panel-empty">
          <SafetyCertificateOutlined className="compliance-panel-empty-icon" />
          <Text type="secondary">当前内容尚未检测</Text>
          <Button
            type="primary"
            icon={<SafetyCertificateOutlined />}
            loading={loading}
            disabled={checkDisabled}
            onClick={onCheck}
          >
            {loading ? '正在检测' : '立即检测'}
          </Button>
        </div>
      </div>
    )
  }

  const officialUnavailable = !report.engine.available || report.isValid === null
  const officialInvalid = report.isValid === false || report.violations.length > 0
  const gzhStrict = report.gzhStrict
  const strictInvalid = Boolean(gzhStrict?.hasError)
  const strictWarning = Boolean(gzhStrict?.hasWarning)
  const status = officialUnavailable
    ? { type: 'warning' as const, icon: ExclamationCircleOutlined, text: '官方规则未验证' }
    : officialInvalid || strictInvalid
      ? { type: 'error' as const, icon: CloseCircleOutlined, text: officialInvalid ? '存在官方规则违规' : '主题严格检查未通过' }
      : strictWarning
        ? { type: 'warning' as const, icon: WarningOutlined, text: '官方检查通过，主题存在警告' }
        : { type: 'success' as const, icon: CheckCircleOutlined, text: '官方微信合规检测通过' }
  const StatusIcon = status.icon

  const items = [
    {
      key: 'official',
      label: (
        <span>
          官方规则结果{' '}
          {officialUnavailable ? <Tag color="orange">未验证</Tag>
            : officialInvalid ? <Badge count={report.violations.length} size="small" />
              : <Tag color="green">通过</Tag>}
        </span>
      ),
      children: officialUnavailable ? (
        <Alert type="warning" showIcon message={report.engine.detail || '官方引擎当前不可用，本文尚未完成验证。'} />
      ) : report.violations.length ? (
        <Collapse
          size="small"
          items={report.violations.map((violation) => ({
            key: violation.key,
            label: `${violation.key}（${violation.items.length} 处）`,
            children: <ViolationGroup violation={violation} />,
          }))}
        />
      ) : (
        <Text type="secondary">官方引擎未发现违规</Text>
      ),
    },
    {
      key: 'engine',
      label: '检测引擎',
      children: (
        <div className="compliance-diagnostics">
          <Text>微信官方 verify-article-structure-spec v{report.engine.version}</Text>
          <Text type="secondary">固定 commit：{report.engine.commit}</Text>
          <Text type="secondary">{report.engine.repository}</Text>
          <Text type="secondary">状态：{report.engine.available ? '可用' : '不可用'}</Text>
          {report.engine.detail && <Text type="secondary">详情：{report.engine.detail}</Text>}
          {report.warnMsgs.map((warning, index) => <Alert key={`${warning}-${index}`} type="warning" showIcon message={warning} />)}
        </div>
      ),
    },
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
  ]

  return (
    <div className="compliance-panel">
      <div className="compliance-panel-actions">
        <Button
          icon={<SafetyCertificateOutlined />}
          loading={loading}
          disabled={checkDisabled}
          onClick={onCheck}
        >
          {loading ? '正在检测' : '重新检测'}
        </Button>
      </div>
      <Alert type={status.type} showIcon icon={<StatusIcon />} title={status.text} style={{ marginBottom: 12 }} />
      <Collapse size="small" defaultActiveKey={officialUnavailable || officialInvalid ? ['official'] : []} items={items} />
    </div>
  )
}
