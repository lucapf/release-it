import { ReactNode } from "react";
import { Stack, Text, ThemeIcon } from "@mantine/core";
import type { Icon } from "@tabler/icons-react";

// Consistent empty-state treatment: a muted icon, a heading, an optional line of
// guidance and an optional call-to-action. Replaces the bare "No X yet." strings
// that were scattered across the app.
export function EmptyState({
  icon: IconCmp,
  title,
  description,
  action,
  py = "xl",
}: {
  icon: Icon;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  py?: string;
}) {
  return (
    <Stack align="center" gap="xs" py={py} px="md">
      <ThemeIcon size={52} radius="xl" variant="light" color="gray">
        <IconCmp size={26} stroke={1.5} />
      </ThemeIcon>
      <Text fw={600} ta="center">
        {title}
      </Text>
      {description && (
        <Text size="sm" c="dimmed" ta="center" maw={420}>
          {description}
        </Text>
      )}
      {action}
    </Stack>
  );
}
