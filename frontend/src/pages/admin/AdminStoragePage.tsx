import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Grid,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  DeleteOutlined,
  CloudUploadOutlined,
  DownloadOutlined,
  EyeOutlined,
  FileImageOutlined,
  FileMarkdownOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  FileUnknownOutlined,
  FileWordOutlined,
  FolderOpenOutlined,
  ReloadOutlined,
  SaveOutlined,
  SettingOutlined,
  ThunderboltOutlined,
  UploadOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import { storageApi } from '../../api/storage'
import { uploadToOss } from '../../api/documents'
import { ApiError } from '../../api/client'
import StorageFilePreview from '../../components/StorageFilePreview'
import type { StorageConfigItem } from '../../types'
import type { StorageObjectItem, StorageObjectListResult, StoragePrefixItem } from '../../api/storage'
import { getStoragePreviewKind, type StoragePreviewKind } from '../../utils/storagePreview'

const { Title, Text } = Typography

type StorageProvider = StorageConfigItem['provider']

const STORAGE_PROVIDER_PROFILES: Record<StorageProvider, {
  label: string
  endpoint: string
  regionOrZone: string
  uploadEndpoint: string
  regionRequired: boolean
  uploadEndpointRequired: boolean
  cors: string
}> = {
  aliyun_oss: {
    label: '阿里云 OSS',
    endpoint: 'oss-cn-hangzhou.aliyuncs.com',
    regionOrZone: '',
    uploadEndpoint: '',
    regionRequired: false,
    uploadEndpointRequired: false,
    cors: '允许 PUT、GET、HEAD；允许 Content-Type 与 x-oss-* 请求头，并暴露 ETag。',
  },
  tencent_cos: {
    label: '腾讯云 COS',
    endpoint: 'cos.ap-shanghai.myqcloud.com',
    regionOrZone: 'ap-shanghai',
    uploadEndpoint: '',
    regionRequired: true,
    uploadEndpointRequired: false,
    cors: '允许 PUT、GET、HEAD；允许 Content-Type 及签名返回的请求头，并暴露 ETag。',
  },
  huawei_obs: {
    label: '华为云 OBS',
    endpoint: 'obs.cn-north-4.myhuaweicloud.com',
    regionOrZone: 'cn-north-4',
    uploadEndpoint: '',
    regionRequired: false,
    uploadEndpointRequired: false,
    cors: '允许 PUT、GET、HEAD；允许 Content-Type 及签名返回的请求头，并暴露 ETag。',
  },
  volcengine_tos: {
    label: '火山引擎 TOS',
    endpoint: 'tos-cn-beijing.volces.com',
    regionOrZone: 'cn-beijing',
    uploadEndpoint: '',
    regionRequired: true,
    uploadEndpointRequired: false,
    cors: '允许 PUT、GET、HEAD；允许 Content-Type 及签名返回的请求头，并暴露 ETag。',
  },
  qiniu_kodo: {
    label: '七牛云 Kodo',
    endpoint: 'https://your-download-domain.example.com',
    regionOrZone: '',
    uploadEndpoint: 'https://up.qiniup.com',
    regionRequired: false,
    uploadEndpointRequired: true,
    cors: '允许 POST、GET、HEAD；允许 multipart 表单字段和 Content-Type，并暴露 ETag。上传 Endpoint 请按存储区域替换。',
  },
}

type FileEntry =
  | (StoragePrefixItem & { entry_type: 'prefix'; size: null; last_modified: null })
  | (StorageObjectItem & { entry_type: 'object' })

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = size / 1024
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[index]}`
}

function storageFileIcon(kind: StoragePreviewKind) {
  if (kind === 'image') return <FileImageOutlined />
  if (kind === 'video') return <VideoCameraOutlined />
  if (kind === 'pdf') return <FilePdfOutlined />
  if (kind === 'docx') return <FileWordOutlined />
  if (kind === 'markdown') return <FileMarkdownOutlined />
  if (kind === 'text') return <FileTextOutlined />
  return <FileUnknownOutlined />
}

export default function AdminStoragePage() {
  const [config, setConfig] = useState<StorageConfigItem | null>(null)
  const [loading, setLoading] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [checkingDirectUpload, setCheckingDirectUpload] = useState(false)
  const [repairing, setRepairing] = useState(false)
  const [listing, setListing] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [deletingKey, setDeletingKey] = useState<string | null>(null)
  const [previewingKey, setPreviewingKey] = useState<string | null>(null)
  const [prefix, setPrefix] = useState('')
  const [objectList, setObjectList] = useState<StorageObjectListResult>({ objects: [], prefixes: [], next_marker: null })
  const [previewObject, setPreviewObject] = useState<StorageObjectItem | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [form] = Form.useForm()
  const selectedProvider = Form.useWatch('provider', form) as StorageProvider | undefined
  const screens = Grid.useBreakpoint()
  const isCompact = !screens.lg
  const provider = selectedProvider ?? config?.provider ?? 'aliyun_oss'
  const providerProfile = STORAGE_PROVIDER_PROFILES[provider]

  const applyConfigToForm = (data: StorageConfigItem) => {
    form.setFieldsValue({
      provider: data.provider,
      endpoint: data.endpoint,
      bucket: data.bucket,
      access_key_id: data.access_key_id,
      access_key_secret: '',
      region_or_zone: data.region_or_zone,
      upload_endpoint: data.upload_endpoint,
      custom_domain: data.custom_domain,
    })
  }

  const handleProviderChange = (nextProvider: StorageProvider) => {
    const nextProfile = STORAGE_PROVIDER_PROFILES[nextProvider]
    const values = form.getFieldsValue(['endpoint', 'region_or_zone', 'upload_endpoint']) as {
      endpoint?: string
      region_or_zone?: string
      upload_endpoint?: string
    }
    form.setFieldsValue({
      provider: nextProvider,
      endpoint: values.endpoint?.trim() ? values.endpoint : nextProfile.endpoint,
      region_or_zone: values.region_or_zone?.trim() ? values.region_or_zone : nextProfile.regionOrZone,
      upload_endpoint: values.upload_endpoint?.trim() ? values.upload_endpoint : nextProfile.uploadEndpoint,
    })
  }

  const loadObjects = async (nextPrefix = prefix, marker = '', append = false) => {
    setListing(true)
    try {
      const data = await storageApi.listObjects(nextPrefix, marker)
      setPrefix(nextPrefix)
      setObjectList((previous) => append ? {
        objects: [...previous.objects, ...data.objects],
        prefixes: [...previous.prefixes, ...data.prefixes],
        next_marker: data.next_marker,
      } : data)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载文件列表失败')
    } finally {
      setListing(false)
    }
  }

  const load = async () => {
    setLoading(true)
    try {
      const data = await storageApi.get()
      setConfig(data)
      applyConfigToForm(data)
      await loadObjects('', '', false)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '加载存储配置失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      const updated = await storageApi.update(values)
      setConfig(updated)
      applyConfigToForm(updated)
      setSettingsOpen(false)
      message.success('存储设置已保存')
      if (updated.configured) void loadObjects('', '', false)
    } catch (err) {
      if (err instanceof ApiError) message.error(String(err.detail))
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    try {
      const result = await storageApi.test()
      if (result.success) message.success(result.message)
      else Modal.error({ title: '连接测试失败', content: result.message })
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '测试连接请求失败')
    } finally {
      setTesting(false)
    }
  }

  const handleDirectUploadCheck = async () => {
    setCheckingDirectUpload(true)
    try {
      const check = await storageApi.startDirectUploadCheck()
      const body = new Blob(['yibanpaiban-direct-upload-check'], { type: check.content_type })
      if (body.size !== check.expected_size) throw new Error('直传测试数据长度不匹配')
      await uploadToOss(
        {
          object_key: check.object_key,
          content_type: check.content_type,
          upload_url: check.upload_url,
          upload_method: check.upload_method,
          upload_headers: check.upload_headers,
          upload_fields: check.upload_fields,
          file_field_name: check.file_field_name,
          expires_in_seconds: check.expires_in_seconds,
        },
        body,
      )
      const result = await storageApi.verifyDirectUploadCheck(check.object_key)
      if (result.success) message.success(result.message)
      else Modal.error({ title: '浏览器直传校验失败', content: result.message })
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : err instanceof Error ? err.message : '浏览器直传检查失败')
    } finally {
      setCheckingDirectUpload(false)
    }
  }

  const handleRepairImageAccess = () => {
    Modal.confirm({
      title: '修复已导入图片访问权限',
      content: '会更新当前推文中的对象存储图片为长期有效的授权链接。',
      onOk: async () => {
        setRepairing(true)
        try {
          const result = await storageApi.repairImageAccess()
          if (result.repaired_count > 0) message.success(result.message)
          else message.warning(result.message)
        } catch (err) {
          message.error(err instanceof ApiError ? String(err.detail) : '修复图片访问权限失败')
        } finally {
          setRepairing(false)
        }
      },
    })
  }

  const handleUpload = async (file: File) => {
    setUploading(true)
    try {
      await storageApi.uploadObject(file, prefix)
      message.success('文件已上传')
      await loadObjects(prefix, '', false)
    } finally {
      setUploading(false)
    }
  }

  const getObjectUrl = async (object: StorageObjectItem) => {
    setPreviewingKey(object.key)
    try {
      return await storageApi.previewObject(object.key)
    } finally {
      setPreviewingKey(null)
    }
  }

  const handlePreview = async (object: StorageObjectItem) => {
    try {
      const result = await getObjectUrl(object)
      setPreviewObject(object)
      setPreviewUrl(result.url)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '获取文件预览失败')
    }
  }

  const handleDownload = async (object: StorageObjectItem) => {
    try {
      const result = await getObjectUrl(object)
      window.open(result.url, '_blank', 'noopener,noreferrer')
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '获取下载链接失败')
    }
  }

  const handleDelete = async (object: StorageObjectItem) => {
    setDeletingKey(object.key)
    try {
      await storageApi.removeObject(object.key)
      message.success('文件已删除')
      await loadObjects(prefix, '', false)
    } catch (err) {
      message.error(err instanceof ApiError ? String(err.detail) : '删除文件失败')
    } finally {
      setDeletingKey(null)
    }
  }

  const entries = useMemo<FileEntry[]>(() => [
    ...objectList.prefixes.map((item) => ({ ...item, entry_type: 'prefix' as const, size: null, last_modified: null })),
    ...objectList.objects.map((item) => ({ ...item, entry_type: 'object' as const })),
  ], [objectList])

  const pathParts = prefix.split('/').filter(Boolean)
  const fileColumns: ColumnsType<FileEntry> = [
    {
      title: '文件',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, item) => item.entry_type === 'prefix' ? (
        <Button type="link" icon={<FolderOpenOutlined />} onClick={() => void loadObjects(item.key)}>{name}</Button>
      ) : (
        <div className="storage-file-cell">
          {getStoragePreviewKind(name) === 'image' && item.thumbnail_url ? (
            <Tooltip title="预览图片">
              <button className="storage-thumbnail" type="button" onClick={() => void handlePreview(item)}>
                <img src={item.thumbnail_url} alt="" onError={(event) => { event.currentTarget.style.display = 'none' }} />
                <FileImageOutlined className="storage-thumbnail-fallback" />
              </button>
            </Tooltip>
          ) : (
            <span className={`storage-file-icon storage-file-icon-${getStoragePreviewKind(name)}`}>
              {storageFileIcon(getStoragePreviewKind(name))}
            </span>
          )}
          <Text className="storage-file-name" title={name}>{name}</Text>
        </div>
      ),
    },
    {
      title: '大小',
      key: 'size',
      width: 120,
      render: (_, item) => item.entry_type === 'prefix' ? <Text type="secondary">文件夹</Text> : formatBytes(item.size),
    },
    {
      title: '更新时间',
      key: 'last_modified',
      width: 190,
      render: (_, item) => item.last_modified ? new Date(item.last_modified).toLocaleString() : '—',
    },
    {
      title: '操作',
      key: 'actions',
      width: 150,
      render: (_, item) => item.entry_type === 'prefix' ? null : (
        <Space size={4}>
          <Tooltip title="预览">
            <Button type="text" icon={<EyeOutlined />} loading={previewingKey === item.key} onClick={() => void handlePreview(item)} />
          </Tooltip>
          <Tooltip title="下载">
            <Button type="text" icon={<DownloadOutlined />} loading={previewingKey === item.key} onClick={() => void handleDownload(item)} />
          </Tooltip>
          <Popconfirm title={`删除文件“${item.name}”？`} onConfirm={() => void handleDelete(item)}>
            <Tooltip title="删除">
              <Button type="text" danger icon={<DeleteOutlined />} loading={deletingKey === item.key} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const activePreviewKind = previewObject ? getStoragePreviewKind(previewObject.name) : 'other'

  const objectActions = (item: StorageObjectItem) => (
    <Space size={4} wrap>
      <Tooltip title="预览">
        <Button type="text" icon={<EyeOutlined />} loading={previewingKey === item.key} onClick={() => void handlePreview(item)} />
      </Tooltip>
      <Tooltip title="下载">
        <Button type="text" icon={<DownloadOutlined />} loading={previewingKey === item.key} onClick={() => void handleDownload(item)} />
      </Tooltip>
      <Popconfirm title={`删除文件“${item.name}”？`} onConfirm={() => void handleDelete(item)}>
        <Tooltip title="删除">
          <Button type="text" danger icon={<DeleteOutlined />} loading={deletingKey === item.key} />
        </Tooltip>
      </Popconfirm>
    </Space>
  )

  return (
    <div className="admin-page">
      <div className="admin-page-header">
        <Space wrap>
          <Title level={4} style={{ margin: 0 }}>文件存储</Title>
          {config && (config.configured ? <Tag color="green">对象存储</Tag> : <Tag color="blue">本地存储</Tag>)}
        </Space>
        <Button icon={<SettingOutlined />} onClick={() => setSettingsOpen(true)}>设置</Button>
      </div>

      <Card loading={loading}>
        {!config?.configured && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="本地存储模式"
            description="未配置对象存储时，上传文件将安全保存在当前服务器；配置后可切换为浏览器直传对象存储。"
          />
        )}
        <>
          <div className="storage-toolbar">
            <Space wrap>
                <Button type="link" onClick={() => void loadObjects('')} style={{ paddingInline: 0 }}>根目录</Button>
                {pathParts.map((part, index) => {
                  const target = pathParts.slice(0, index + 1).join('/')
                  return <Button key={target} type="link" onClick={() => void loadObjects(target)}>/ {part}</Button>
                })}
              </Space>
              <Space wrap>
                <Button icon={<ReloadOutlined />} loading={listing} onClick={() => void loadObjects(prefix)}>刷新</Button>
              <Upload
                showUploadList={false}
                disabled={uploading}
                customRequest={({ file, onSuccess, onError }) => {
                  void handleUpload(file as File).then(() => onSuccess?.({}), (error: Error) => onError?.(error))
                }}
              >
                <Button type="primary" icon={<UploadOutlined />} loading={uploading}>上传文件</Button>
              </Upload>
            </Space>
          </div>
          {isCompact ? (
              <div className="responsive-card-list storage-card-list" aria-label="文件列表">
                {entries.length === 0 ? (
                  <Empty description="当前目录暂无文件" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                ) : entries.map((item) => (
                  <article className="responsive-data-card" key={`${item.entry_type}-${item.key}`}>
                    {item.entry_type === 'prefix' ? (
                      <Button type="link" icon={<FolderOpenOutlined />} onClick={() => void loadObjects(item.key)}>{item.name}</Button>
                    ) : (
                      <>
                        <div className="storage-file-cell">
                          {getStoragePreviewKind(item.name) === 'image' && item.thumbnail_url ? (
                            <button className="storage-thumbnail" type="button" onClick={() => void handlePreview(item)}>
                              <img src={item.thumbnail_url} alt="" onError={(event) => { event.currentTarget.style.display = 'none' }} />
                              <FileImageOutlined className="storage-thumbnail-fallback" />
                            </button>
                          ) : (
                            <span className={`storage-file-icon storage-file-icon-${getStoragePreviewKind(item.name)}`}>
                              {storageFileIcon(getStoragePreviewKind(item.name))}
                            </span>
                          )}
                          <Text className="storage-file-name" title={item.name}>{item.name}</Text>
                        </div>
                        <div className="responsive-data-card-meta">
                          <span>{formatBytes(item.size)}</span>
                          <span>{item.last_modified ? new Date(item.last_modified).toLocaleString() : '—'}</span>
                        </div>
                        <div className="responsive-data-card-actions">{objectActions(item)}</div>
                      </>
                    )}
                  </article>
                ))}
              </div>
            ) : (
              <Table
                rowKey={(item) => `${item.entry_type}-${item.key}`}
                columns={fileColumns}
                dataSource={entries}
                loading={listing}
                pagination={false}
                locale={{ emptyText: '当前目录暂无文件' }}
              />
          )}
          {objectList.next_marker && (
            <Button style={{ marginTop: 12 }} loading={listing} onClick={() => void loadObjects(prefix, objectList.next_marker ?? '', true)}>
              加载更多
            </Button>
          )}
        </>
      </Card>

      <Modal
        title="对象存储设置"
        open={settingsOpen}
        className="storage-settings-modal"
        onCancel={() => setSettingsOpen(false)}
        footer={(
          <div className="storage-settings-footer">
            <Space>
              {config?.configured && (
                <>
                  <Button icon={<ThunderboltOutlined />} loading={testing} onClick={handleTest}>测试连接</Button>
                  <Button icon={<CloudUploadOutlined />} loading={checkingDirectUpload} onClick={handleDirectUploadCheck}>测试浏览器直传</Button>
                  <Button icon={<ReloadOutlined />} loading={repairing} onClick={handleRepairImageAccess}>修复已导入图片</Button>
                </>
              )}
            </Space>
            <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>保存</Button>
          </div>
        )}
        width={640}
        destroyOnHidden
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={config?.configured
            ? `配置 ${providerProfile.label} 后，PDF/Word 导入由浏览器直传，应用服务器不会转发原文件或解析图片。`
            : '当前使用本地存储，所有上传由应用服务器接收并保存在服务器磁盘。'}
          description={config?.configured
            ? `请在 Bucket 控制台为实际前端域名配置 CORS：${providerProfile.cors}`
            : '完成对象存储配置后，文档导入可切换为浏览器直传，并适合多实例或无状态部署。'}
        />
        <Form form={form} layout="vertical">
          <Form.Item name="provider" label="存储厂商" initialValue="aliyun_oss" rules={[{ required: true }]}>
            <Select
              options={Object.entries(STORAGE_PROVIDER_PROFILES).map(([value, profile]) => ({ value, label: profile.label }))}
              onChange={handleProviderChange}
            />
          </Form.Item>
          <Form.Item name="endpoint" label={provider === 'qiniu_kodo' ? '下载 Endpoint / 域名' : 'Endpoint'} rules={[{ required: true, message: '请输入 Endpoint' }]}>
            <Input placeholder={providerProfile.endpoint} />
          </Form.Item>
          <Form.Item
            name="region_or_zone"
            label="区域 / Zone"
            rules={providerProfile.regionRequired ? [{ required: true, message: `请输入 ${providerProfile.label} 的区域 / Zone` }] : undefined}
            extra={providerProfile.regionRequired ? '请填写厂商控制台中的区域标识。' : undefined}
          >
            <Input placeholder={providerProfile.regionOrZone || '可选'} />
          </Form.Item>
          <Form.Item
            name="upload_endpoint"
            label="浏览器上传 Endpoint"
            rules={providerProfile.uploadEndpointRequired ? [{ required: true, message: '请输入七牛云上传 Endpoint' }] : undefined}
            extra={provider === 'qiniu_kodo' ? '七牛使用 multipart POST；请选择与 Bucket 区域相符的上传域名。' : '留空即可，浏览器直传使用 Endpoint。'}
          >
            <Input placeholder={providerProfile.uploadEndpoint || '可选'} />
          </Form.Item>
          <Form.Item name="bucket" label="Bucket 名称" rules={[{ required: true, message: '请输入 Bucket 名称' }]}>
            <Input placeholder="my-bucket" />
          </Form.Item>
          <Form.Item name="access_key_id" label="AccessKey ID" rules={[{ required: true, message: '请输入 AccessKey ID' }]}>
            <Input autoComplete="off" placeholder="LTAI..." />
          </Form.Item>
          <Form.Item
            name="access_key_secret"
            label="AccessKey Secret"
            extra={config?.configured ? `留空表示不修改现有密钥（当前：${config.access_key_secret_masked}）` : undefined}
            rules={[{ required: !config?.configured, message: '请输入 AccessKey Secret' }]}
          >
            <Input.Password autoComplete="off" placeholder={config?.configured ? '留空则不修改' : '••••••••'} />
          </Form.Item>
          <Form.Item name="custom_domain" label="自定义域名（可选）">
            <Input placeholder="https://static.example.com" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={previewObject?.name ?? '文件预览'}
        open={Boolean(previewObject && previewUrl)}
        onCancel={() => {
          setPreviewObject(null)
          setPreviewUrl(null)
        }}
        footer={previewObject && (
          <Button icon={<DownloadOutlined />} onClick={() => void handleDownload(previewObject)}>在新窗口打开</Button>
        )}
        width={activePreviewKind === 'image' ? 860 : activePreviewKind === 'docx' ? 1120 : 980}
        className="storage-preview-modal"
        destroyOnHidden
      >
        {previewObject && previewUrl && (
          <StorageFilePreview
            filename={previewObject.name}
            size={previewObject.size}
            url={previewUrl}
            kind={activePreviewKind}
          />
        )}
      </Modal>
    </div>
  )
}
