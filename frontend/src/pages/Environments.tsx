import { useQuery } from "@tanstack/react-query";
import { Card, Group, SimpleGrid, Skeleton, Stack, Text, ThemeIcon, Title } from "@mantine/core";
import { IconServer, IconWorld } from "@tabler/icons-react";
import { listEnvironments } from "../api/client";
import { EmptyState } from "../components/EmptyState";

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
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
          {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} h={92} radius="md" />)}
        </SimpleGrid>
      ) : envs.length === 0 ? (
        <Card padding="xl">
          <EmptyState
            icon={IconWorld}
            title="No environments configured"
            description="Target environments for installation will appear here once they are provisioned."
          />
        </Card>
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="md">
          {envs.map((e) => (
            <Card key={e.id} padding="md">
              <Group gap="sm" wrap="nowrap" align="flex-start">
                <ThemeIcon variant="light" color="indigo" size={38} radius="md">
                  <IconServer size={20} stroke={1.6} />
                </ThemeIcon>
                <div>
                  <Title order={5}>{e.name}</Title>
                  <Text size="sm" c="dimmed">{e.description || "—"}</Text>
                </div>
              </Group>
            </Card>
          ))}
        </SimpleGrid>
      )}
    </Stack>
  );
}
