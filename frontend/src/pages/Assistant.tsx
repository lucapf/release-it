import { Stack, Text, Title } from "@mantine/core";
import { AssistantChat } from "../components/AssistantChat";

// Full-page assistant (deep-linkable at /assistant). The same chat is also
// reachable from the top-bar "Chat" button, which opens it in a drawer.
export function AssistantPage() {
  return (
    <Stack gap="lg" h="calc(100vh - 108px)">
      <div>
        <Title order={2}>Assistant</Title>
        <Text c="dimmed">
          Ask about release status or have the assistant create releases and upload documents for you.
        </Text>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        <AssistantChat />
      </div>
    </Stack>
  );
}
