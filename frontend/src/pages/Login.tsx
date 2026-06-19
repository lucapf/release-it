import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Button,
  Center,
  Paper,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  ThemeIcon,
  Title,
} from "@mantine/core";
import { IconAlertCircle, IconRocket } from "@tabler/icons-react";
import { useAuth } from "../auth/AuthContext";

export function LoginPage() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await signIn(username, password);
      navigate("/dashboard");
    } catch {
      setError("Invalid credentials");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Center mih="100vh" bg="var(--mantine-color-gray-1)">
      <Paper withBorder shadow="md" p="xl" radius="lg" w={380}>
        <Stack gap="lg">
          <Stack gap={4} align="center">
            <ThemeIcon size={52} radius="md" variant="gradient" gradient={{ from: "indigo", to: "grape" }}>
              <IconRocket size={28} />
            </ThemeIcon>
            <Title order={2} mt="xs">ReleaseIT</Title>
            <Text size="sm" c="dimmed">Sign in to the release management platform</Text>
          </Stack>
          <form onSubmit={onSubmit}>
            <Stack gap="sm">
              <TextInput
                label="Username"
                value={username}
                onChange={(e) => setUsername(e.currentTarget.value)}
                autoFocus
              />
              <PasswordInput
                label="Password"
                value={password}
                onChange={(e) => setPassword(e.currentTarget.value)}
              />
              {error && (
                <Alert color="red" variant="light" icon={<IconAlertCircle size={16} />} p="xs">
                  {error}
                </Alert>
              )}
              <Button type="submit" fullWidth loading={loading} mt="xs">
                Sign in
              </Button>
            </Stack>
          </form>
        </Stack>
      </Paper>
    </Center>
  );
}
