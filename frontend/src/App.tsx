import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import {
  ActionIcon,
  AppShell,
  Avatar,
  Badge,
  Box,
  Burger,
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
  IconMoon,
  IconRocket,
  IconSettings,
  IconSun,
  IconWorld,
} from "@tabler/icons-react";
import { useAuth } from "./auth/AuthContext";
import { LoginPage } from "./pages/Login";
import { DashboardPage } from "./pages/Dashboard";
import { ProductDetailPage } from "./pages/ProductDetail";
import { EnvironmentsPage } from "./pages/Environments";
import { ConfigurationPage } from "./pages/Configuration";

function Protected({ children }: { children: JSX.Element }) {
  const { authenticated } = useAuth();
  return authenticated ? children : <Navigate to="/login" replace />;
}

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: IconLayoutDashboard },
  { to: "/environments", label: "Environments", icon: IconWorld },
  { to: "/configuration", label: "Configuration", icon: IconSettings },
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
  const [opened, { toggle, close }] = useDisclosure();
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
            <ColorSchemeToggle />
            <UserMenu />
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        <div style={{ flex: 1 }}>
          {NAV.map((item) => {
            const Icon = item.icon;
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
        path="/environments"
        element={<Protected><Shell><EnvironmentsPage /></Shell></Protected>}
      />
      <Route
        path="/configuration"
        element={<Protected><Shell><ConfigurationPage /></Shell></Protected>}
      />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
