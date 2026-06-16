import { useQuery } from "@tanstack/react-query";
import { Card, Group, Loader, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { listEnvironments } from "../api/client";

export function EnvironmentsPage() {
  const { data: envs = [], isLoading } = useQuery({
    queryKey: ["environments"],
    queryFn: listEnvironments,
  });

  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>Environments</Title>
        <Text c="dimmed">Target environments for installation.</Text>
      </div>
      {isLoading ? (
        <Group justify="center" py="xl"><Loader /></Group>
      ) : envs.length === 0 ? (
        <Text c="dimmed">No environments configured.</Text>
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
          {envs.map((e) => (
            <Card key={e.id} withBorder padding="md" radius="md">
              <Title order={5}>{e.name}</Title>
              <Text size="sm" c="dimmed">{e.description || "—"}</Text>
            </Card>
          ))}
        </SimpleGrid>
      )}
    </Stack>
  );
}
