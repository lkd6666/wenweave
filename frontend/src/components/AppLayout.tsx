import { useEffect, useMemo, useState } from 'react'
import { Layout, Menu, Avatar, Button, Drawer, Dropdown, Grid, Typography } from 'antd'
import type { MenuProps } from 'antd'
import {
  FileTextOutlined,
  RobotOutlined,
  CloudOutlined,
  TeamOutlined,
  UserOutlined,
  LogoutOutlined,
  KeyOutlined,
  MenuOutlined,
  SendOutlined,
  HistoryOutlined,
  DashboardOutlined,
  SettingOutlined,
  PictureOutlined,
  FontSizeOutlined,
} from '@ant-design/icons'
import { DesktopOutlined, MoonOutlined, SunOutlined } from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router'
import { useAuthStore } from '../store/authStore'
import ChangePasswordModal from './ChangePasswordModal'
import GlobalUserQuestionNotifications from './GlobalUserQuestionNotifications'
import ViewportFitGuide from './ViewportFitGuide'
import { useAppTheme } from '../theme/appTheme'
import { brandingAssetUrl, useAppBranding } from '../brand/appBranding'

const { Header, Sider, Content } = Layout
const { Text } = Typography

const adminMenuGroups = [
  {
    key: 'admin-system',
    paths: ['/admin/models', '/admin/storage'],
  },
  {
    key: 'admin-content',
    paths: ['/admin/branding', '/admin/image-library', '/admin/article-typography', '/admin/wechat-accounts'],
  },
  {
    key: 'admin-users',
    paths: ['/admin/users', '/admin/user-groups', '/admin/operation-logs'],
  },
] as const

export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const { preference, resolvedTheme, setPreference } = useAppTheme()
  const { branding } = useAppBranding()
  const [changePasswordOpen, setChangePasswordOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => location.pathname.startsWith('/editor/'))
  const [navigationOpen, setNavigationOpen] = useState(false)
  const [openMenuKeys, setOpenMenuKeys] = useState<string[]>(() => {
    const group = adminMenuGroups.find(({ paths }) => paths.some((path) => location.pathname.startsWith(path)))
    return group ? [group.key] : []
  })
  const screens = Grid.useBreakpoint()
  const isCompact = !screens.lg
  const isEditorPage = location.pathname.startsWith('/editor/')

  useEffect(() => {
    if (isEditorPage) setSidebarCollapsed(true)
  }, [isEditorPage])

  useEffect(() => {
    const group = adminMenuGroups.find(({ paths }) => paths.some((path) => location.pathname.startsWith(path)))
    if (group) {
      setOpenMenuKeys((keys) => (keys.includes(group.key) ? keys : [...keys, group.key]))
    }
  }, [location.pathname])

  const menuItems = useMemo(() => {
    const items: MenuProps['items'] = [
      { key: '/', icon: <DashboardOutlined />, label: '工作看板' },
      { key: '/workbench', icon: <FileTextOutlined />, label: '推文工作台' },
    ]
    if (user?.role === 'admin') {
      items.push(
        {
          key: 'admin-system',
          icon: <SettingOutlined />,
          label: '系统配置',
          children: [
            { key: '/admin/models', icon: <RobotOutlined />, label: 'AI 模型管理' },
            { key: '/admin/storage', icon: <CloudOutlined />, label: '存储设置' },
          ],
        },
        {
          key: 'admin-content',
          icon: <FileTextOutlined />,
          label: '内容管理',
          children: [
            { key: '/admin/branding', icon: <SettingOutlined />, label: '品牌设置' },
            { key: '/admin/image-library', icon: <PictureOutlined />, label: '图片库设置' },
            { key: '/admin/article-typography', icon: <FontSizeOutlined />, label: '正文排版' },
            { key: '/admin/wechat-accounts', icon: <SendOutlined />, label: '公众号账号' },
          ],
        },
        {
          key: 'admin-users',
          icon: <TeamOutlined />,
          label: '用户与审计',
          children: [
            { key: '/admin/users', icon: <TeamOutlined />, label: '用户管理' },
            { key: '/admin/user-groups', icon: <TeamOutlined />, label: '用户组' },
            { key: '/admin/operation-logs', icon: <HistoryOutlined />, label: '操作日志' },
          ],
        },
      )
    }
    return items
  }, [user])

  const selectedKey = useMemo(() => {
    const group = adminMenuGroups.find(({ paths }) => paths.some((path) => location.pathname === path || location.pathname.startsWith(`${path}/`)))
    if (group) {
      const path = group.paths.find((item) => location.pathname === item || location.pathname.startsWith(`${item}/`))
      if (path) return [path]
    }

    if (location.pathname.startsWith('/editor/')) return ['/workbench']
    if (location.pathname === '/') return ['/']
    return location.pathname.startsWith('/workbench') ? ['/workbench'] : []
  }, [location.pathname])

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

  const navigateTo = (path: string) => {
    navigate(path)
    setNavigationOpen(false)
  }

  const navigationMenu = (
    <Menu
      mode="inline"
      selectedKeys={selectedKey}
      openKeys={openMenuKeys}
      items={menuItems}
      onClick={({ key }) => navigateTo(String(key))}
      onOpenChange={setOpenMenuKeys}
      style={{ borderInlineEnd: 'none' }}
    />
  )

  const logoUrl = brandingAssetUrl(branding.logo_url, branding.updated_at) ?? '/favicon.svg'

  return (
    <Layout className="app-layout">
      {!isCompact && (
        <Sider
          width={220}
          collapsedWidth={64}
          collapsible
          collapsed={sidebarCollapsed}
          onCollapse={setSidebarCollapsed}
          theme={resolvedTheme}
          className="app-sider"
        >
          <div className="app-brand" title={branding.system_name}>
            <img className="app-brand-logo" src={logoUrl} alt="" />
            <span className="app-brand-label">{branding.system_name}</span>
          </div>
          {navigationMenu}
        </Sider>
      )}
      <Layout>
        <Header className="app-header">
          <div className="app-header-leading">
            {isCompact && (
              <Button
                aria-label="打开导航菜单"
                type="text"
                className="app-navigation-trigger"
                icon={<MenuOutlined />}
                onClick={() => setNavigationOpen(true)}
              />
            )}
            {isCompact && (
              <div className="app-compact-brand" title={branding.system_name}>
                <img className="app-compact-brand-logo" src={logoUrl} alt="" />
                <span>{branding.system_name}</span>
              </div>
            )}
          </div>
          <div className="app-header-actions">
            <Dropdown trigger={['click']} menu={themeMenu}>
              <Button
                aria-label="切换主题"
                type="text"
                className="app-theme-trigger"
                icon={preference === 'system' ? <DesktopOutlined /> : resolvedTheme === 'dark' ? <MoonOutlined /> : <SunOutlined />}
              />
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
                <Text className="app-user-name">{user?.display_name || user?.username}</Text>
                <Text className="app-user-role" type="secondary" style={{ fontSize: 12 }}>
                  {user?.role === 'admin' ? '管理员' : '普通用户'}
                </Text>
              </div>
            </Dropdown>
          </div>
        </Header>
        <Content className="app-content">
          <Outlet />
        </Content>
      </Layout>
      <GlobalUserQuestionNotifications systemName={branding.system_name} iconUrl={logoUrl} />
      <ViewportFitGuide />
      <Drawer
        title={branding.system_name}
        placement="left"
        size={280}
        open={isCompact && navigationOpen}
        onClose={() => setNavigationOpen(false)}
        className="app-navigation-drawer"
        styles={{ body: { padding: 0 } }}
      >
        {navigationMenu}
      </Drawer>
      <ChangePasswordModal open={changePasswordOpen} onClose={() => setChangePasswordOpen(false)} />
    </Layout>
  )
}
