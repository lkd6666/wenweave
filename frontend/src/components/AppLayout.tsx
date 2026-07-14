import { useMemo, useState } from 'react'
import { Layout, Menu, Avatar, Button, Dropdown, Tooltip, Typography } from 'antd'
import type { MenuProps } from 'antd'
import {
  FileTextOutlined,
  RobotOutlined,
  CloudOutlined,
  TeamOutlined,
  UserOutlined,
  LogoutOutlined,
  KeyOutlined,
  } from '@ant-design/icons'
import { DesktopOutlined, MoonOutlined, SunOutlined } from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import ChangePasswordModal from './ChangePasswordModal'
import { useAppTheme } from '../theme/appTheme'

const { Header, Sider, Content } = Layout
const { Text } = Typography

export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const { preference, resolvedTheme, setPreference } = useAppTheme()
  const [changePasswordOpen, setChangePasswordOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  const menuItems = useMemo(() => {
    const items: MenuProps['items'] = [
      { key: '/', icon: <FileTextOutlined />, label: '排版工作台' },
    ]
    if (user?.role === 'admin') {
      items.push(
        { key: '/admin/models', icon: <RobotOutlined />, label: 'AI 模型管理' },
        { key: '/admin/storage', icon: <CloudOutlined />, label: '存储设置' },
        { key: '/admin/users', icon: <TeamOutlined />, label: '用户管理' },
        { key: '/admin/user-groups', icon: <TeamOutlined />, label: '用户组' },
      )
    }
    return items
  }, [user])

  const selectedKey = useMemo(() => {
    const match = menuItems?.find(
      (item) =>
        item &&
        String(item.key) !== '/' &&
        (location.pathname === String(item.key) ||
          location.pathname.startsWith(`${String(item.key)}/`)),
    )

    if (match) return [String(match.key)]

    return location.pathname === '/' || location.pathname.startsWith('/editor/') ? ['/'] : []
  }, [menuItems, location.pathname])

  const userMenu: MenuProps['items'] = [
    { key: 'change-password', icon: <KeyOutlined />, label: '修改密码' },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录' },
  ]

  const themeMenu: MenuProps = {
    selectable: true,
    selectedKeys: [preference],
    items: [
      { key: 'light', icon: <SunOutlined />, label: '白天模式' },
      { key: 'dark', icon: <MoonOutlined />, label: '黑暗模式' },
      { key: 'system', icon: <DesktopOutlined />, label: '跟随系统' },
    ],
    onClick: ({ key }) => {
      if (key === 'light' || key === 'dark' || key === 'system') setPreference(key)
    },
  }

  return (
    <Layout className="app-layout">
      <Sider
        width={220}
        collapsedWidth={64}
        collapsible
        collapsed={sidebarCollapsed}
        onCollapse={setSidebarCollapsed}
        theme={resolvedTheme}
        className="app-sider"
      >
        <div className="app-brand">
          {sidebarCollapsed ? 'AI' : '公众号 AI 排版'}
        </div>
        <Menu
          mode="inline"
          selectedKeys={selectedKey}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ borderInlineEnd: 'none' }}
        />
      </Sider>
      <Layout>
        <Header className="app-header">
          <Dropdown trigger={['click']} menu={themeMenu}>
            <Tooltip title={`主题：${preference === 'system' ? `跟随系统（当前${resolvedTheme === 'dark' ? '黑暗' : '白天'}）` : preference === 'dark' ? '黑暗模式' : '白天模式'}`}>
              <Button
                aria-label="切换主题"
                type="text"
                className="app-theme-trigger"
                icon={preference === 'system' ? <DesktopOutlined /> : resolvedTheme === 'dark' ? <MoonOutlined /> : <SunOutlined />}
              />
            </Tooltip>
          </Dropdown>
          <Dropdown
            trigger={['click']}
            menu={{
              items: userMenu,
              onClick: ({ key }) => {
                if (key === 'logout') {
                  logout()
                  navigate('/login')
                } else if (key === 'change-password') {
                  setChangePasswordOpen(true)
                }
              },
            }}
          >
            <div className="app-user-menu-trigger">
              <Avatar size="small" icon={<UserOutlined />} />
              <Text>{user?.display_name || user?.username}</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {user?.role === 'admin' ? '管理员' : '普通用户'}
              </Text>
            </div>
          </Dropdown>
        </Header>
        <Content className="app-content">
          <Outlet />
        </Content>
      </Layout>
      <ChangePasswordModal open={changePasswordOpen} onClose={() => setChangePasswordOpen(false)} />
    </Layout>
  )
}
