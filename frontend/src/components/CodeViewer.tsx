import { Button, Space, Typography, message } from 'antd'
import { CopyOutlined, SaveOutlined } from '@ant-design/icons'
import CodeMirror from '@uiw/react-codemirror'
import { html as htmlLanguage } from '@codemirror/lang-html'
import { githubDark, githubLight } from '@uiw/codemirror-theme-github'
import { useAppTheme } from '../theme/appTheme'

const { Text } = Typography

interface CodeViewerProps {
  html: string
  onChange: (html: string) => void
  onSave: () => void
  saving?: boolean
  disabled?: boolean
}

export default function CodeViewer({ html, onChange, onSave, saving, disabled = false }: CodeViewerProps) {
  const { resolvedTheme } = useAppTheme()
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(html)
      message.success('HTML 代码已复制到剪贴板')
    } catch {
      message.error('复制失败，请手动选择复制')
    }
  }

  return (
    <div className="code-viewer">
      <div className="code-viewer-toolbar">
        <Text type="secondary">HTML 源码（可手动微调后保存）</Text>
        <Space>
          <Button size="small" icon={<CopyOutlined />} onClick={handleCopy}>
            复制代码
          </Button>
          <Button size="small" type="primary" icon={<SaveOutlined />} loading={saving} disabled={disabled} onClick={onSave}>
            保存修改
          </Button>
        </Space>
      </div>
      <CodeMirror
        className="code-viewer-editor"
        value={html}
        height="100%"
        extensions={[htmlLanguage()]}
        theme={resolvedTheme === 'dark' ? githubDark : githubLight}
        basicSetup={{
          lineNumbers: true,
          foldGutter: true,
          highlightActiveLine: true,
          highlightSelectionMatches: true,
          bracketMatching: true,
        }}
        editable={!disabled}
        onChange={onChange}
      />
    </div>
  )
}
