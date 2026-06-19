import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Modal,
  SimpleGrid,
  Skeleton,
  Stack,
  Text,
  TextInput,
  ThemeIcon,
  Title,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import {
  IconBox,
  IconCircleCheck,
  IconClockHour4,
  IconPencil,
  IconPlus,
} from "@tabler/icons-react";
import { getOverview, createProduct, ProductOverview, Release } from "../api/client";
import { StateBadge } from "../components/StateBadge";
import { EmptyState } from "../components/EmptyState";
import { ReleaseKind } from "../lib/releases";
import { notifyApiError } from "../lib/errors";

// --- Top-of-page summary ----------------------------------------------------
// Which release slot the dashboard is filtered by. `null` shows every product.
type ProductFilter = "stable" | "approval" | "draft" | null;

function StatCard({
  icon: Icon,
  label,
  value,
  color,
  active,
  onClick,
}: {
  icon: typeof IconBox;
  label: string;
  value: number;
  color: string;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <Card
      padding="md"
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      aria-pressed={onClick ? !!active : undefined}
      style={onClick ? { cursor: "pointer" } : undefined}
      withBorder={active}
      styles={active ? { root: { borderColor: `var(--mantine-color-${color}-filled)` } } : undefined}
    >
      <Group gap="sm" wrap="nowrap">
        <ThemeIcon variant={active ? "filled" : "light"} color={color} size={42} radius="md">
          <Icon size={22} stroke={1.6} />
        </ThemeIcon>
        <div>
          <Text fz={28} fw={700} lh={1}>
            {value}
          </Text>
          <Text size="xs" c="dimmed" tt="uppercase" fw={600} mt={4}>
            {label}
          </Text>
        </div>
      </Group>
    </Card>
  );
}

function SummaryBar({
  products,
  filter,
  onFilter,
}: {
  products: ProductOverview[];
  filter: ProductFilter;
  onFilter: (f: ProductFilter) => void;
}) {
  const stable = products.filter((p) => p.last_stable).length;
  const approval = products.filter((p) => p.under_approval).length;
  const drafts = products.filter((p) => p.draft).length;
  // Clicking the active card again clears the filter (toggle behaviour).
  const toggle = (f: Exclude<ProductFilter, null>) => () => onFilter(filter === f ? null : f);
  return (
    <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="md">
      <StatCard
        icon={IconBox}
        label="Products"
        value={products.length}
        color="indigo"
        active={filter === null}
        onClick={() => onFilter(null)}
      />
      <StatCard
        icon={IconCircleCheck}
        label="With stable"
        value={stable}
        color="teal"
        active={filter === "stable"}
        onClick={toggle("stable")}
      />
      <StatCard
        icon={IconClockHour4}
        label="In approval"
        value={approval}
        color="yellow"
        active={filter === "approval"}
        onClick={toggle("approval")}
      />
      <StatCard
        icon={IconPencil}
        label="Open drafts"
        value={drafts}
        color="gray"
        active={filter === "draft"}
        onClick={toggle("draft")}
      />
    </SimpleGrid>
  );
}

// A compact secondary slot (draft / under-approval) linking through to the
// product view with that release preselected.
function MiniSlot({
  label,
  productId,
  kind,
  release,
}: {
  label: string;
  productId: number;
  kind: ReleaseKind;
  release: Release | null;
}) {
  return (
    <Card withBorder shadow="none" padding="xs" radius="md" bg="light-dark(var(--mantine-color-gray-0), var(--mantine-color-dark-6))">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>{label}</Text>
      {release ? (
        <Group justify="space-between" mt={2} wrap="nowrap">
          <Anchor component={Link} to={`/products/${productId}?kind=${kind}`} fw={600} size="sm">
            v{release.version}
          </Anchor>
          <StateBadge state={release.state} size="sm" />
        </Group>
      ) : (
        <Text size="sm" c="dimmed" mt={2}>— none —</Text>
      )}
    </Card>
  );
}

function ProductCard({ product }: { product: ProductOverview }) {
  const stable = product.last_stable;
  return (
    <Card padding="lg">
      <Group justify="space-between" mb="sm" wrap="nowrap">
        <Anchor component={Link} to={`/products/${product.id}`} lineClamp={1}>
          <Title order={4}>{product.name}</Title>
        </Anchor>
        <Badge variant="outline" color="gray" style={{ flexShrink: 0 }}>
          {product.release_count} release{product.release_count === 1 ? "" : "s"}
        </Badge>
      </Group>

      {/* Last stable version is the headline of every product. */}
      <Card
        withBorder
        shadow="none"
        radius="md"
        padding="md"
        bg={stable ? "light-dark(var(--mantine-color-teal-0), var(--mantine-color-dark-6))" : "light-dark(var(--mantine-color-gray-0), var(--mantine-color-dark-6))"}
      >
        <Text size="xs" c="dimmed" tt="uppercase" fw={700}>Last stable</Text>
        {stable ? (
          <Group justify="space-between" mt={4}>
            <Anchor component={Link} to={`/products/${product.id}?kind=stable`} fw={700} fz="xl">
              v{stable.version}
            </Anchor>
            <StateBadge state={stable.state} emphasis />
          </Group>
        ) : (
          <Text c="dimmed" mt={4}>No stable release yet.</Text>
        )}
      </Card>

      <SimpleGrid cols={2} spacing="xs" mt="sm">
        <MiniSlot label="Under approval" productId={product.id} kind="approval" release={product.under_approval} />
        <MiniSlot label="Draft" productId={product.id} kind="draft" release={product.draft} />
      </SimpleGrid>

      <Button component={Link} to={`/products/${product.id}`} variant="light" fullWidth mt="md">
        Open product
      </Button>
    </Card>
  );
}

// --- New-product modal ------------------------------------------------------
function CreateProductModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const add = useMutation({
    mutationFn: () => createProduct(name),
    onSuccess: () => {
      setName("");
      qc.invalidateQueries({ queryKey: ["overview"] });
      notifications.show({ message: "Product created", color: "teal" });
      onClose();
    },
    onError: (e: any) => notifyApiError(e, "Failed to create product"),
  });
  return (
    <Modal opened={opened} onClose={onClose} title="New product" size="sm">
      <Stack gap="md">
        <TextInput
          label="Product name"
          placeholder="e.g. Payments service"
          value={name}
          data-autofocus
          onChange={(e) => setName(e.currentTarget.value)}
          onKeyDown={(e) => e.key === "Enter" && name && add.mutate()}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button disabled={!name} loading={add.isPending} onClick={() => add.mutate()}>
            Create product
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function DashboardSkeleton() {
  return (
    <Stack gap="lg">
      <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="md">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} h={74} radius="md" />)}
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="lg">
        {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} h={240} radius="md" />)}
      </SimpleGrid>
    </Stack>
  );
}

export function DashboardPage() {
  const { data: products = [], isLoading } = useQuery({
    queryKey: ["overview"],
    queryFn: getOverview,
  });
  const [opened, { open, close }] = useDisclosure(false);
  const [filter, setFilter] = useState<ProductFilter>(null);

  const visible = products.filter((p) => {
    if (filter === "stable") return !!p.last_stable;
    if (filter === "approval") return !!p.under_approval;
    if (filter === "draft") return !!p.draft;
    return true;
  });

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>Dashboard</Title>
          <Text c="dimmed">Last stable version of every product, with quick access to drafts and approvals.</Text>
        </div>
        <Button leftSection={<IconPlus size={16} />} onClick={open}>
          New product
        </Button>
      </Group>

      <CreateProductModal opened={opened} onClose={close} />

      {isLoading ? (
        <DashboardSkeleton />
      ) : products.length === 0 ? (
        <Card padding="xl">
          <EmptyState
            icon={IconBox}
            title="No products yet"
            description="Create your first product to start tracking its releases, checks and approvals."
            action={
              <Button mt="sm" leftSection={<IconPlus size={16} />} onClick={open}>
                New product
              </Button>
            }
          />
        </Card>
      ) : (
        <>
          <SummaryBar products={products} filter={filter} onFilter={setFilter} />
          {visible.length === 0 ? (
            <Card padding="xl">
              <EmptyState
                icon={IconBox}
                title="No matching products"
                description="No products match the selected filter."
                action={
                  <Button mt="sm" variant="light" onClick={() => setFilter(null)}>
                    Show all products
                  </Button>
                }
              />
            </Card>
          ) : (
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="lg">
              {visible.map((p) => (
                <ProductCard key={p.id} product={p} />
              ))}
            </SimpleGrid>
          )}
        </>
      )}
    </Stack>
  );
}
