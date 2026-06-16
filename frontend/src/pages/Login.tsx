import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Button,
  Center,
  Group,
  Paper,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  ThemeIcon,
  Title,
} from "@mantine/core";
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
      <Paper withBorder shadow="md" p="xl" radius="md" w={360}>
        <Stack gap="lg">
          <Group gap="xs">
            <ThemeIcon size="lg" variant="gradient" gradient={{ from: "indigo", to: "grape" }}>
              🚀
            </ThemeIcon>
            <Title order={2}>ReleaseIT</Title>
          </Group>
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
              {error && <Text c="red" size="sm">{error}</Text>}
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
