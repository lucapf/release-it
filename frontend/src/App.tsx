import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ActionIcon,
  AppShell,
  Avatar,
  Badge,
  Box,
  Burger,
  Button,
  Drawer,
  Group,
  Menu,
  NavLink,
  Text,
  ThemeIcon,
  Title,
  Tooltip,
  useComputedColorScheme,
  useMantineColorScheme,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconLayoutDashboard,
  IconLogout,
  IconMessageChatbot,
  IconMoon,
  IconRocket,
  IconSettings,
  IconSun,
} from "@tabler/icons-react";
import { useAuth } from "./auth/AuthContext";
import { LoginPage } from "./pages/Login";
import { DashboardPage } from "./pages/Dashboard";
import { ProductDetailPage } from "./pages/ProductDetail";
import {
  CONFIG_SECTIONS,
  ProjectsPage,
  DocumentTypesPage,
  WorkflowPage,
  TrackerPage,
  GitHostingPage,
  AssistantActionsPage,
} from "./pages/Configuration";
import { LlmPage } from "./pages/Llm";
import { AssistantPage } from "./pages/Assistant";
import { AssistantChat } from "./components/AssistantChat";
import { UsersPage } from "./pages/Users";
import { getOverview } from "./api/client";

function Protected({ children }: { children: JSX.Element }) {
  const { authenticated } = useAuth();
  return authenticated ? children : <Navigate to="/login" replace />;
}

// Gate a route to administrators; everyone else is bounced to the dashboard.
function AdminOnly({ children }: { children: JSX.Element }) {
  const { hasRole } = useAuth();
  return hasRole("Administrator") ? children : <Navigate to="/dashboard" replace />;
}

type NavItem = {
  to: string;
  label: string;
  icon: typeof IconLayoutDashboard;
  adminOnly?: boolean;
  // When present, the item renders as an expandable node with these sub-links.
  children?: { to: string; label: string }[];
};

const NAV: NavItem[] = [
  { to: "/dashboard", label: "Dashboard", icon: IconLayoutDashboard },
  {
    to: "/configuration",
    label: "Configuration",
    icon: IconSettings,
    adminOnly: true,
    // One sub-item per section, each on its own dedicated page under
    // /configuration/<path>.
    children: CONFIG_SECTIONS.map((s) => ({
      to: `/configuration/${s.path}`,
      label: s.label,
    })),
  },
];

function ColorSchemeToggle() {
  const { setColorScheme } = useMantineColorScheme();
  const computed = useComputedColorScheme("light", { getInitialValueInEffect: true });
  const dark = computed === "dark";
  return (
    <Tooltip label={dark ? "Light mode" : "Dark mode"}>
      <ActionIcon
        variant="subtle"
        color="gray"
        size="lg"
        aria-label="Toggle color scheme"
        onClick={() => setColorScheme(dark ? "light" : "dark")}
      >
        {dark ? <IconSun size={18} /> : <IconMoon size={18} />}
      </ActionIcon>
    </Tooltip>
  );
}

function UserMenu() {
  const { user, signOut } = useAuth();
  const name = user?.subject || "User";
  const initials = name.slice(0, 2).toUpperCase();
  return (
    <Menu position="bottom-end" width={240} withArrow>
      <Menu.Target>
        <Group gap="xs" style={{ cursor: "pointer" }}>
          <Avatar color="indigo" radius="xl" size={34}>
            {initials}
          </Avatar>
          <Box style={{ lineHeight: 1.1 }} visibleFrom="sm">
            <Text size="sm" fw={600}>
              {name}
            </Text>
            <Text size="xs" c="dimmed">
              {user?.roles[0] ?? "No role"}
            </Text>
          </Box>
        </Group>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>Signed in as {name}</Menu.Label>
        <Group gap={6} px="sm" pb="xs" wrap="wrap">
          {user && user.roles.length > 0 ? (
            user.roles.map((r) => (
              <Badge key={r} size="sm" variant="light" color="indigo">
                {r}
              </Badge>
            ))
          ) : (
            <Text size="xs" c="dimmed">
              No roles assigned
            </Text>
          )}
        </Group>
        <Menu.Divider />
        <Menu.Item
          color="red"
          leftSection={<IconLogout size={16} />}
          onClick={signOut}
        >
          Sign out
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}

function Shell({ children }: { children: JSX.Element }) {
  const { pathname } = useLocation();
  const { hasRole } = useAuth();
  const [opened, { toggle, close }] = useDisclosure();
  const [chatOpened, chat] = useDisclosure(false);
  // The Dashboard node expands into one sub-link per product, so operators can
  // jump straight to a product from the sidebar.
  const { data: products = [] } = useQuery({ queryKey: ["overview"], queryFn: getOverview });
  const nav = NAV.filter((item) => !item.adminOnly || hasRole("Administrator")).map((item) =>
    item.to === "/dashboard" && products.length > 0
      ? { ...item, children: products.map((p) => ({ to: `/products/${p.id}`, label: p.name })) }
      : item,
  );
  return (
    <AppShell
      header={{ height: 60 }}
      navbar={{
        width: 240,
        breakpoint: "sm",
        collapsed: { mobile: !opened },
      }}
      padding="lg"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <ThemeIcon
              variant="gradient"
              gradient={{ from: "indigo", to: "grape" }}
              radius="md"
              size="lg"
            >
              <IconRocket size={20} />
            </ThemeIcon>
            <Title order={3}>ReleaseIT</Title>
          </Group>
          <Group gap="sm">
            <Button
              variant="light"
              color="indigo"
              leftSection={<IconMessageChatbot size={18} />}
              onClick={chat.open}
            >
              Chat
            </Button>
            <ColorSchemeToggle />
            <UserMenu />
          </Group>
        </Group>
      </AppShell.Header>

      {/* Global assistant launcher: opens the chat from any page. */}
      <Drawer
        opened={chatOpened}
        onClose={chat.close}
        position="right"
        size="lg"
        title={
          <Group gap="xs">
            <ThemeIcon variant="light" color="indigo" radius="xl" size="md">
              <IconMessageChatbot size={16} />
            </ThemeIcon>
            <Text fw={600}>Assistant</Text>
          </Group>
        }
        styles={{
          content: { display: "flex", flexDirection: "column" },
          body: { flex: 1, minHeight: 0, display: "flex", flexDirection: "column" },
        }}
      >
        <AssistantChat />
      </Drawer>

      <AppShell.Navbar p="sm">
        <div style={{ flex: 1 }}>
          {nav.map((item) => {
            const Icon = item.icon;
            if (item.children) {
              // Expandable node: exact-match active so sibling routes nested
              // under the same prefix (e.g. /configuration/llm) don't light up
              // the parent, but keep the node open on any of its subpages.
              const withinSection =
                pathname.startsWith(item.to) ||
                item.children.some((c) => pathname.startsWith(c.to));
              return (
                <NavLink
                  key={item.to}
                  component={Link}
                  to={item.to}
                  label={item.label}
                  leftSection={<Icon size={18} stroke={1.6} />}
                  active={pathname === item.to}
                  defaultOpened={withinSection}
                  mb={4}
                >
                  {item.children.map((child) => (
                    <NavLink
                      key={child.to}
                      component={Link}
                      to={child.to}
                      label={child.label}
                      onClick={close}
                      active={pathname === child.to}
                    />
                  ))}
                </NavLink>
              );
            }
            return (
              <NavLink
                key={item.to}
                component={Link}
                to={item.to}
                label={item.label}
                onClick={close}
                leftSection={<Icon size={18} stroke={1.6} />}
                active={pathname.startsWith(item.to)}
                mb={4}
              />
            );
          })}
        </div>
        <Text size="xs" c="dimmed" p="xs">
          Release management platform
        </Text>
      </AppShell.Navbar>

      <AppShell.Main bg="light-dark(var(--mantine-color-gray-0), var(--mantine-color-dark-8))">
        {children}
      </AppShell.Main>
    </AppShell>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/dashboard"
        element={<Protected><Shell><DashboardPage /></Shell></Protected>}
      />
      <Route
        path="/products/:productId"
        element={<Protected><Shell><ProductDetailPage /></Shell></Protected>}
      />
      <Route
        path="/assistant"
        element={<Protected><Shell><AssistantPage /></Shell></Protected>}
      />
      <Route path="/configuration" element={<Navigate to="/configuration/projects" replace />} />
      <Route
        path="/configuration/users"
        element={<Protected><Shell><AdminOnly><UsersPage /></AdminOnly></Shell></Protected>}
      />
      <Route
        path="/configuration/projects"
        element={<Protected><Shell><AdminOnly><ProjectsPage /></AdminOnly></Shell></Protected>}
      />
      <Route
        path="/configuration/document-types"
        element={<Protected><Shell><AdminOnly><DocumentTypesPage /></AdminOnly></Shell></Protected>}
      />
      <Route
        path="/configuration/workflow"
        element={<Protected><Shell><AdminOnly><WorkflowPage /></AdminOnly></Shell></Protected>}
      />
      <Route
        path="/configuration/tracker"
        element={<Protected><Shell><AdminOnly><TrackerPage /></AdminOnly></Shell></Protected>}
      />
      <Route
        path="/configuration/git"
        element={<Protected><Shell><AdminOnly><GitHostingPage /></AdminOnly></Shell></Protected>}
      />
      <Route
        path="/configuration/assistant-actions"
        element={<Protected><Shell><AdminOnly><AssistantActionsPage /></AdminOnly></Shell></Protected>}
      />
      <Route
        path="/configuration/llm"
        element={<Protected><Shell><AdminOnly><LlmPage /></AdminOnly></Shell></Protected>}
      />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
