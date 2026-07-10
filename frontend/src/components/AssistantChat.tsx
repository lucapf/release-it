import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Group,
  Paper,
  ScrollArea,
  Stack,
  Text,
  Textarea,
  ThemeIcon,
  TypographyStylesProvider,
} from "@mantine/core";
import {
  IconArrowUp,
  IconCheck,
  IconFileTypePdf,
  IconMarkdown,
  IconRobot,
  IconTool,
  IconUser,
} from "@tabler/icons-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ChatAction,
  ChatDocumentRef,
  ChatMessage,
  downloadDocumentVersion,
  sendChat,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { notifyApiError } from "../lib/errors";

// Renders an assistant turn as Markdown. GFM adds tables, task lists and
// strikethrough (the assistant is prompted to answer in Markdown); raw HTML is
// intentionally NOT enabled, so model output can't inject markup. Mantine's
// TypographyStylesProvider gives the native elements theme-consistent spacing;
// wide content (tables, code) scrolls within the bubble instead of overflowing.
function AssistantMarkdown({ content }: { content: string }) {
  return (
    <TypographyStylesProvider
      style={{ fontSize: "var(--mantine-font-size-sm)", overflowX: "auto" }}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Open any links the assistant emits safely in a new tab.
          a: ({ node, ref, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </TypographyStylesProvider>
  );
}

// One rendered turn: the wire message plus, for assistant turns, the tools it ran
// and any documents it surfaced for download.
type Turn = ChatMessage & { actions?: ChatAction[]; documents?: ChatDocumentRef[] };

// A document the assistant surfaced — rendered as authenticated download buttons
// (Markdown to edit, PDF to read), reusing the same token-aware download the
// website uses. The chat can't stream a file itself, so this is how "download
// via chat" works.
function DocumentCard({ doc }: { doc: ChatDocumentRef }) {
  const dl = useMutation({
    mutationFn: (format?: "pdf") =>
      doc.version_id == null
        ? Promise.reject(new Error("This document has no uploaded version yet"))
        : downloadDocumentVersion(doc.release_id, doc.document_id, doc.version_id, doc.filename, format),
    onError: (e: any) => notifyApiError(e, "Download failed"),
  });
  const approved = doc.status === "APPROVED";
  return (
    <Paper withBorder radius="md" px="sm" py="xs">
      <Group justify="space-between" wrap="nowrap" gap="sm">
        <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
          <Text size="sm" fw={600} truncate>{doc.title}</Text>
          <Badge size="xs" variant="light" color="grape">{doc.doc_type}</Badge>
          <Badge
            size="xs"
            variant={approved ? "filled" : "light"}
            color={approved ? "teal" : "gray"}
            leftSection={approved ? <IconCheck size={10} /> : undefined}
          >
            {approved ? "Approved" : "Draft"}
          </Badge>
        </Group>
        <Group gap={6} wrap="nowrap">
          <Button
            size="compact-xs"
            variant="light"
            leftSection={<IconMarkdown size={14} />}
            loading={dl.isPending}
            onClick={() => dl.mutate(undefined)}
          >
            .md
          </Button>
          {doc.has_pdf && (
            <Button
              size="compact-xs"
              variant="light"
              color="red"
              leftSection={<IconFileTypePdf size={14} />}
              loading={dl.isPending}
              onClick={() => dl.mutate("pdf")}
            >
              .pdf
            </Button>
          )}
        </Group>
      </Group>
    </Paper>
  );
}

// Starter prompts covering the assistant's core capabilities.
const SUGGESTIONS = [
  "Give me a status report of all running releases, with their blockers.",
  "Create a new release for a product.",
  "Draft release notes for a release and upload them as a document.",
];

function ActionPill({ action }: { action: ChatAction }) {
  return (
    <Badge
      variant="light"
      color={action.ok ? "teal" : "red"}
      leftSection={<IconTool size={12} />}
      styles={{ root: { textTransform: "none" } }}
    >
      {action.summary || action.tool}
    </Badge>
  );
}

function MessageBubble({ turn }: { turn: Turn }) {
  const isUser = turn.role === "user";
  return (
    <Group align="flex-start" justify={isUser ? "flex-end" : "flex-start"} wrap="nowrap">
      {!isUser && (
        <ThemeIcon variant="light" color="indigo" radius="xl" size={34}>
          <IconRobot size={18} />
        </ThemeIcon>
      )}
      <Stack gap={6} maw="80%" align={isUser ? "flex-end" : "flex-start"}>
        {turn.actions && turn.actions.length > 0 && (
          <Group gap={6}>
            {turn.actions.map((a, i) => (
              <ActionPill key={i} action={a} />
            ))}
          </Group>
        )}
        <Paper
          withBorder
          radius="md"
          px="md"
          py="sm"
          maw="100%"
          bg={
            isUser
              ? "var(--mantine-color-indigo-6)"
              : "light-dark(var(--mantine-color-white), var(--mantine-color-dark-6))"
          }
        >
          {isUser ? (
            // The operator's own text is plain — render verbatim, keeping newlines.
            <Text
              size="sm"
              c="white"
              style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}
            >
              {turn.content}
            </Text>
          ) : (
            <AssistantMarkdown content={turn.content} />
          )}
        </Paper>
        {turn.documents && turn.documents.length > 0 && (
          <Stack gap={6} w="100%">
            {turn.documents.map((d) => (
              <DocumentCard key={d.document_id} doc={d} />
            ))}
          </Stack>
        )}
      </Stack>
      {isUser && (
        <ThemeIcon variant="light" color="gray" radius="xl" size={34}>
          <IconUser size={18} />
        </ThemeIcon>
      )}
    </Group>
  );
}

// The chat surface — message list + composer — filling its parent's height. Used
// both by the full-page /assistant route and by the top-bar "Chat" drawer.
export function AssistantChat() {
  const { user } = useAuth();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const viewport = useRef<HTMLDivElement>(null);

  const scrollToBottom = () =>
    viewport.current?.scrollTo({ top: viewport.current.scrollHeight, behavior: "smooth" });
  useEffect(scrollToBottom, [turns]);

  const chat = useMutation({
    // Send the whole transcript (roles + content only) so the backend stays stateless.
    mutationFn: (history: Turn[]) =>
      sendChat(history.map(({ role, content }) => ({ role, content }))),
    onSuccess: (res) =>
      setTurns((t) => [
        ...t,
        { role: "assistant", content: res.reply, actions: res.actions, documents: res.documents },
      ]),
    onError: (e: any) => notifyApiError(e, "The assistant couldn't respond"),
  });

  const send = (text: string) => {
    const content = text.trim();
    if (!content || chat.isPending) return;
    const next: Turn[] = [...turns, { role: "user", content }];
    setTurns(next);
    setInput("");
    chat.mutate(next);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends; Shift+Enter inserts a newline (standard chat ergonomics).
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  };

  const empty = turns.length === 0;

  return (
    <Paper
      withBorder
      radius="md"
      style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0 }}
    >
      <ScrollArea style={{ flex: 1 }} viewportRef={viewport} p="lg">
        {empty ? (
          <Stack align="center" justify="center" gap="md" py="xl" mih={240}>
            <ThemeIcon variant="light" color="indigo" radius="xl" size={56}>
              <IconRobot size={30} />
            </ThemeIcon>
            <Text fw={600} ta="center">
              Hi {user?.subject || "there"} — how can I help with your releases?
            </Text>
            <Stack gap="xs" align="center">
              {SUGGESTIONS.map((s) => (
                <Paper
                  key={s}
                  withBorder
                  radius="md"
                  px="md"
                  py="xs"
                  style={{ cursor: "pointer", maxWidth: 520 }}
                  onClick={() => send(s)}
                >
                  <Text size="sm">{s}</Text>
                </Paper>
              ))}
            </Stack>
          </Stack>
        ) : (
          <Stack gap="lg">
            {turns.map((t, i) => (
              <MessageBubble key={i} turn={t} />
            ))}
            {chat.isPending && (
              <Group align="center" gap="xs">
                <ThemeIcon variant="light" color="indigo" radius="xl" size={34}>
                  <IconRobot size={18} />
                </ThemeIcon>
                <Text size="sm" c="dimmed">
                  Thinking…
                </Text>
              </Group>
            )}
          </Stack>
        )}
      </ScrollArea>

      <Box p="sm" style={{ borderTop: "1px solid var(--mantine-color-default-border)" }}>
        <Textarea
          placeholder="Ask about releases, or tell the assistant what to do… (Enter to send, Shift+Enter for a new line)"
          autosize
          minRows={1}
          maxRows={6}
          value={input}
          onChange={(e) => setInput(e.currentTarget.value)}
          onKeyDown={onKeyDown}
          disabled={chat.isPending}
          rightSection={
            <ActionIcon
              variant="filled"
              color="indigo"
              radius="xl"
              size="lg"
              aria-label="Send"
              loading={chat.isPending}
              disabled={!input.trim()}
              onClick={() => send(input)}
            >
              <IconArrowUp size={18} />
            </ActionIcon>
          }
          rightSectionWidth={52}
        />
      </Box>
    </Paper>
  );
}
