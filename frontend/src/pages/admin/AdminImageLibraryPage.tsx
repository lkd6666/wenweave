import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Checkbox, Empty, Input, Modal, Radio, Space, Spin, Typography, message } from 'antd'
import { SaveOutlined } from '@ant-design/icons'
import { imageLibraryApi } from '../../api/imageLibrary'
import { ApiError } from '../../api/client'
import type { ImageLibraryAsset, ImageLibraryMode } from '../../types'

const { Text, Title } = Typography

export default function AdminImageLibraryPage() {
  const [mode, setMode] = useState<ImageLibraryMode>('personal')
  const [savedMode, setSavedMode] = useState<ImageLibraryMode>('personal')
  const [assets, setAssets] = useState<ImageLibraryAsset[]>([])
  const [sharedIds, setSharedIds] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [settings, allAssets] = await Promise.all([imageLibraryApi.settings(), imageLibraryApi.settingsAssets()])
      setMode(settings.mode)
      setSavedMode(settings.mode)
      setAssets(allAssets)
      setSharedIds(allAssets.filter((asset) => asset.is_shared).map((asset) => asset.id))
    } catch (error) {
      message.error(error instanceof ApiError ? String(error.detail) : '加载图片库设置失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    return normalized ? assets.filter((asset) => `${asset.name} ${asset.owner_name}`.toLowerCase().includes(normalized)) : assets
  }, [assets, query])

  const persist = async () => {
    setSaving(true)
    try {
      await imageLibraryApi.updateSettings(mode, mode === 'shared' ? sharedIds : [])
      setSavedMode(mode)
      message.success('图片库模式已保存')
      await load()
    } catch (error) {
      message.error(error instanceof ApiError ? String(error.detail) : '保存图片库设置失败')
    } finally {
      setSaving(false)
    }
  }

  const save = () => {
    if (savedMode !== 'personal' || mode !== 'shared') {
      void persist()
      return
    }
    Modal.confirm({
      title: '确认切换为全员共享图库',
      content: `已选择 ${sharedIds.length} 张历史图片公开给全员。未勾选图片不会公开，后续可在此继续调整。`,
      okText: '确认切换',
      cancelText: '返回选择',
      onOk: persist,
    })
  }

  return <div className="admin-page image-library-settings-page">
    <header className="admin-page-header"><div><Title level={3}>图片库设置</Title><Text type="secondary">统一控制图片素材是个人隔离还是全员共享。</Text></div></header>
    <Card className="image-library-settings-card">
      <Radio.Group value={mode} onChange={(event) => setMode(event.target.value)}>
        <Space orientation="vertical" size={12}>
          <Radio value="personal"><strong>个人图库</strong><Text type="secondary">每位用户只能查看和管理自己上传、生成或使用过的图片。</Text></Radio>
          <Radio value="shared"><strong>全员共享图库</strong><Text type="secondary">所有用户均可使用、重命名或移出共享集合中的图片。</Text></Radio>
        </Space>
      </Radio.Group>
      {savedMode === 'personal' && mode === 'shared' && <Alert type="warning" showIcon message="切换不会自动公开历史个人图片" description="请在下方勾选允许加入全员共享图库的历史图片。保存后，共享模式产生的新图片会自动加入共享集合。" />}
      <Button type="primary" icon={<SaveOutlined />} loading={saving} disabled={loading} onClick={save}>保存设置</Button>
    </Card>
    {mode === 'shared' && <Card title={`共享历史图片（已选 ${sharedIds.length}/${assets.length}）`} className="image-library-settings-assets" extra={<Input.Search allowClear placeholder="搜索图片或上传者" value={query} onChange={(event) => setQuery(event.target.value)} />}>
      {loading ? <Spin /> : filtered.length ? <>
        <Checkbox checked={assets.length > 0 && sharedIds.length === assets.length} indeterminate={sharedIds.length > 0 && sharedIds.length < assets.length} onChange={(event) => setSharedIds(event.target.checked ? assets.map((asset) => asset.id) : [])}>全选全部历史图片</Checkbox>
        <div className="admin-image-library-grid">{filtered.map((asset) => <label className={`admin-image-library-item${sharedIds.includes(asset.id) ? ' is-selected' : ''}`} key={asset.id}>
          <Checkbox checked={sharedIds.includes(asset.id)} onChange={(event) => setSharedIds((ids) => event.target.checked ? [...ids, asset.id] : ids.filter((id) => id !== asset.id))} />
          <img src={asset.url} alt={asset.name} />
          <span><strong title={asset.name}>{asset.name}</strong><small>{asset.owner_name}</small></span>
        </label>)}</div>
      </> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的历史图片" />}
    </Card>}
  </div>
}
