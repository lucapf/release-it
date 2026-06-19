import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  MultiSelect,
  PasswordInput,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconPencil, IconTrash, IconPlus } from "@tabler/icons-react";
import {
  listUsers,
  createUser,
  updateUser,
  deleteUser,
  User,
  ROLES,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { notifyApiError } from "../lib/errors";

const USERS_KEY = ["users"];

function CreateUserModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [roles, setRoles] = useState<string[]>([]);

  // Reset the form each time the modal opens.
  useEffect(() => {
    if (opened) {
      setUsername("");
      setPassword("");
      setEmail("");
      setRoles([]);
    }
  }, [opened]);

  const create = useMutation({
    mutationFn: () =>
      createUser({
        username: username.trim(),
        password,
        email: email.trim() || undefined,
        roles,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: USERS_KEY });
      notifications.show({ message: "User created", color: "teal" });
      onClose();
    },
    onError: (e: any) => notifyApiError(e, "Could not create user"),
  });

  return (
    <Modal opened={opened} onClose={onClose} title="Add user" size="md">
      <Stack gap="md">
        <TextInput
          label="Username"
          data-autofocus
          value={username}
          onChange={(e) => setUsername(e.currentTarget.value)}
        />
        <PasswordInput
          label="Password"
          value={password}
          onChange={(e) => setPassword(e.currentTarget.value)}
        />
        <TextInput
          label="Email"
          placeholder="optional"
          value={email}
          onChange={(e) => setEmail(e.currentTarget.value)}
        />
        <MultiSelect
          label="Roles"
          data={ROLES}
          value={roles}
          onChange={setRoles}
          placeholder="Assign roles"
          comboboxProps={{ withinPortal: true }}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button
            disabled={!username.trim() || !password}
            loading={create.isPending}
            onClick={() => create.mutate()}
          >
            Create user
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function EditUserModal({ user, onClose }: { user: User | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [roles, setRoles] = useState<string[]>([]);
  useEffect(() => {
    if (user) {
      setEmail(user.email ?? "");
      setRoles(user.roles);
    }
  }, [user]);

  const save = useMutation({
    mutationFn: () => updateUser(user!.id, { email: email.trim(), roles }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: USERS_KEY });
      notifications.show({ message: "User updated", color: "teal" });
      onClose();
    },
    onError: (e: any) => notifyApiError(e, "Could not update user"),
  });

  return (
    <Modal opened={!!user} onClose={onClose} title={`Edit ${user?.username ?? "user"}`} size="md">
      <Stack gap="md">
        <TextInput
          label="Email"
          placeholder="optional"
          value={email}
          onChange={(e) => setEmail(e.currentTarget.value)}
        />
        <MultiSelect
          label="Roles"
          data={ROLES}
          value={roles}
          onChange={setRoles}
          placeholder="Assign roles"
          comboboxProps={{ withinPortal: true }}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button loading={save.isPending} onClick={() => save.mutate()}>Save changes</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function DeleteUserModal({ user, onClose }: { user: User | null; onClose: () => void }) {
  const qc = useQueryClient();
  const del = useMutation({
    mutationFn: () => deleteUser(user!.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: USERS_KEY });
      notifications.show({ message: "User deleted", color: "teal" });
      onClose();
    },
    onError: (e: any) => notifyApiError(e, "Could not delete user"),
  });

  return (
    <Modal opened={!!user} onClose={onClose} title="Delete user" size="md">
      <Stack gap="md">
        <Alert color="red" variant="light">
          This permanently deletes the account <b>{user?.username}</b>. This cannot be undone.
        </Alert>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button color="red" loading={del.isPending} onClick={() => del.mutate()}>Delete user</Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function UsersPage() {
  const { user: me } = useAuth();
  const { data: users = [], isLoading } = useQuery({ queryKey: USERS_KEY, queryFn: listUsers });
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [deleting, setDeleting] = useState<User | null>(null);

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={2}>Users</Title>
          <Text c="dimmed">Manage accounts and role assignments.</Text>
        </div>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setCreating(true)}>
          Add user
        </Button>
      </Group>

      <Card withBorder radius="md" padding="lg">
        {isLoading ? (
          <Loader />
        ) : users.length === 0 ? (
          <Text c="dimmed" size="sm">No users yet.</Text>
        ) : (
          <Table.ScrollContainer minWidth={560}>
            <Table verticalSpacing="sm" highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Username</Table.Th>
                  <Table.Th>Email</Table.Th>
                  <Table.Th>Roles</Table.Th>
                  <Table.Th w={90} />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {users.map((u) => {
                  const isSelf = me?.subject === u.username;
                  return (
                    <Table.Tr key={u.id}>
                      <Table.Td fw={600}>
                        {u.username}
                        {isSelf && (
                          <Badge ml={6} size="xs" variant="light" color="gray">you</Badge>
                        )}
                      </Table.Td>
                      <Table.Td>
                        {u.email ? u.email : <Text size="sm" c="dimmed">— not set —</Text>}
                      </Table.Td>
                      <Table.Td>
                        {u.roles.length === 0 ? (
                          <Text size="sm" c="dimmed">— none —</Text>
                        ) : (
                          <Group gap={4} wrap="wrap">
                            {u.roles.map((r) => (
                              <Badge key={r} size="sm" variant="light" color="indigo">{r}</Badge>
                            ))}
                          </Group>
                        )}
                      </Table.Td>
                      <Table.Td>
                        <Group gap={4} wrap="nowrap">
                          <ActionIcon variant="subtle" color="gray" aria-label="Edit user"
                            onClick={() => setEditing(u)}>
                            <IconPencil size={16} />
                          </ActionIcon>
                          <ActionIcon variant="subtle" color="red" aria-label="Delete user"
                            disabled={isSelf}
                            title={isSelf ? "You cannot delete your own account" : undefined}
                            onClick={() => setDeleting(u)}>
                            <IconTrash size={16} />
                          </ActionIcon>
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Card>

      <CreateUserModal opened={creating} onClose={() => setCreating(false)} />
      <EditUserModal user={editing} onClose={() => setEditing(null)} />
      <DeleteUserModal user={deleting} onClose={() => setDeleting(null)} />
    </Stack>
  );
}
