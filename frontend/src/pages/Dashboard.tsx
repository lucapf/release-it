import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { getOverview, createProduct, ProductOverview, Release } from "../api/client";
import { StateBadge } from "../components/StateBadge";

// One "slot" on a product card: the current draft or under-approval release,
// linking through to the product detail page (with an empty state otherwise).
function ReleaseSlot({
  label,
  productId,
  release,
}: {
  label: string;
  productId: number;
  release: Release | null;
}) {
  return (
    <Card withBorder padding="sm" radius="md" bg="var(--mantine-color-gray-0)">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
      {release ? (
        <Group justify="space-between" mt={4}>
          <Anchor component={Link} to={`/products/${productId}`} fw={600}>
            v{release.version}
          </Anchor>
          <StateBadge state={release.state} />
        </Group>
      ) : (
        <Text size="sm" c="dimmed" mt={4}>
          — none —
        </Text>
      )}
    </Card>
  );
}

function ProductCard({ product }: { product: ProductOverview }) {
  return (
    <Card withBorder shadow="sm" radius="md" padding="lg">
      <Group justify="space-between" mb="xs">
        <Anchor component={Link} to={`/products/${product.id}`}>
          <Title order={4}>{product.name}</Title>
        </Anchor>
        <Badge variant="outline" color="gray">
          {product.release_count} release{product.release_count === 1 ? "" : "s"}
        </Badge>
      </Group>
      <Stack gap="sm">
        <ReleaseSlot label="Current draft" productId={product.id} release={product.draft} />
        <ReleaseSlot label="Under approval" productId={product.id} release={product.under_approval} />
      </Stack>
      <Button
        component={Link}
        to={`/products/${product.id}`}
        variant="light"
        fullWidth
        mt="md"
      >
        Open product
      </Button>
    </Card>
  );
}

export function DashboardPage() {
  const qc = useQueryClient();
  const { data: products = [], isLoading } = useQuery({
    queryKey: ["overview"],
    queryFn: getOverview,
  });
  const [name, setName] = useState("");
  const add = useMutation({
    mutationFn: () => createProduct(name),
    onSuccess: () => {
      setName("");
      qc.invalidateQueries({ queryKey: ["overview"] });
      notifications.show({ message: "Product created", color: "teal" });
    },
    onError: () => notifications.show({ message: "Failed to create product", color: "red" }),
  });

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>Dashboard</Title>
          <Text c="dimmed">Draft and under-approval version of every product.</Text>
        </div>
        <Group gap="xs">
          <TextInput
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            placeholder="New product name"
          />
          <Button disabled={!name} loading={add.isPending} onClick={() => add.mutate()}>
            Create
          </Button>
        </Group>
      </Group>

      {isLoading ? (
        <Group justify="center" py="xl">
          <Loader />
        </Group>
      ) : products.length === 0 ? (
        <Card withBorder padding="xl">
          <Text c="dimmed" ta="center">
            No products yet. Create your first product to get started.
          </Text>
        </Card>
      ) : (
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="lg">
          {products.map((p) => (
            <ProductCard key={p.id} product={p} />
          ))}
        </SimpleGrid>
      )}
    </Stack>
  );
}
