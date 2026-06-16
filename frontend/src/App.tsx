import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import {
  AppShell,
  Group,
  NavLink,
  Title,
  Button,
  Text,
  ThemeIcon,
} from "@mantine/core";
import { useAuth } from "./auth/AuthContext";
import { LoginPage } from "./pages/Login";
import { DashboardPage } from "./pages/Dashboard";
import { ProductDetailPage } from "./pages/ProductDetail";
import { EnvironmentsPage } from "./pages/Environments";

function Protected({ children }: { children: JSX.Element }) {
  const { authenticated } = useAuth();
  return authenticated ? children : <Navigate to="/login" replace />;
}

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: "📊" },
  { to: "/environments", label: "Environments", icon: "🌐" },
];

function Shell({ children }: { children: JSX.Element }) {
  const { signOut } = useAuth();
  const { pathname } = useLocation();
  return (
    <AppShell
      header={{ height: 60 }}
      navbar={{ width: 240, breakpoint: "sm" }}
      padding="lg"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <ThemeIcon variant="gradient" gradient={{ from: "indigo", to: "grape" }} radius="md">
              🚀
            </ThemeIcon>
            <Title order={3}>ReleaseIT</Title>
          </Group>
          <Button variant="subtle" color="gray" onClick={signOut}>
            Sign out
          </Button>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            component={Link}
            to={item.to}
            label={item.label}
            leftSection={<span>{item.icon}</span>}
            active={pathname.startsWith(item.to)}
          />
        ))}
        <Text size="xs" c="dimmed" mt="auto" p="xs" pos="absolute" bottom={8}>
          Release management platform
        </Text>
      </AppShell.Navbar>

      <AppShell.Main>{children}</AppShell.Main>
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
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
