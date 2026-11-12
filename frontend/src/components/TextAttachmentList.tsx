import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Modal, Space, Spin, Typography } from 'antd'
import { FileTextOutlined } from '@ant-design/icons'
import type { ChatTextAttachmentDraft } from '../types'
import { chatTextsApi } from '../api/chatTexts'
import type { TextAttachmentPage } from '../api/chatTexts'

export default function TextAttachmentList({ items, onRemove, onRetry }: {
  items: ChatTextAttachmentDraft[]
  onRemove?: (item: ChatTextAttachmentDraft) => void
  onRetry?: (item: ChatTextAttachmentDraft) => void
}) {
  const [selected, setSelected] = useState<ChatTextAttachmentDraft | null>(null)
  const [page, setPage] = useState<TextAttachmentPage | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const version = useRef(0)
  useEffect(() => () => { version.current += 1 }, [])
  const selectedPresent = !selected || items.some(item => item.id === selected.id)
  useEffect(() => {
    if (!selectedPresent) { version.current += 1; setSelected(null); setPage(null); setError('') }
  }, [selectedPresent])
  const load = async (item: ChatTextAttachmentDraft, start = 0) => {
    const token = ++version.current
    setSelected(item); setLoading(true); setError('')
    try {
      const result = await chatTextsApi.read(item.document_id, item.id, start)
      if (token === version.current) setPage(result)
    } catch (err) {
      if (token === version.current) setError(err instanceof Error ? err.message : '读取失败')
    } finally { if (token === version.current) setLoading(false) }
  }
  return <>
    <div className="chat-text-attachments" aria-label="文本附件" style={{ display: 'grid', gap: 8, margin: '8px 0', minWidth: 0 }}>
      {items.map(item => <div key={item.id} style={{ border: '1px solid var(--ant-color-border, #d9d9d9)', borderRadius: 8, padding: '8px 10px', minWidth: 0 }}>
        <Space wrap size={4} style={{ maxWidth: '100%' }}>
          <FileTextOutlined />
          <Typography.Text ellipsis style={{ maxWidth: 220 }} title={item.filename}>{item.filename}</Typography.Text>
          <small>{Math.ceil(item.size / 1024)} KB · {item.lines} 行</small>
          {item.status === 'uploading' ? <><Spin size="small" /><small>上传中</small></>
            : item.status === 'error' ? <Button size="small" onClick={() => onRetry?.(item)}>重试上传</Button>
              : <Button size="small" type="link" onClick={() => { void load(item) }}>查看文本</Button>}
          {onRemove && <Button size="small" type="text" disabled={item.status === 'uploading'} onClick={() => onRemove(item)} aria-label={`移除 ${item.filename}`}>移除</Button>}
        </Space>
        {item.error && <Alert type="error" message={item.error} showIcon />}
      </div>)}
    </div>
    <Modal open={Boolean(selected) && selectedPresent} title={selected?.filename} width={800}
      onCancel={() => { version.current += 1; setSelected(null); setPage(null) }}
      footer={<Space wrap><small>只预览当前片段，模型也会按需分页读取。</small>
        {selected && <Button disabled={loading} onClick={() => { void load(selected) }}>回到开头</Button>}
        <Button disabled={loading || page?.next_cursor == null} onClick={() => {
          if (selected && page?.next_cursor != null) void load(selected, page.next_cursor)
        }}>下一段</Button></Space>}>
      {error && <Alert type="error" message={error} />}
      <Spin spinning={loading}><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: '60vh', overflow: 'auto', minHeight: 100 }}>{page?.content ?? ''}</pre></Spin>
      {page && <small>字符 {page.start}–{page.end} / {page.characters}</small>}
    </Modal>
  </>
}
