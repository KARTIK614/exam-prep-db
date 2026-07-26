import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { adminApi, useAdminUsers } from '@/lib/api/admin';

/**
 * AdminUsers — user table with role/is_active toggles.
 */
export default function AdminUsers() {
  const users = useAdminUsers();

  const toggleRole = async (id: number, currentRole: string) => {
    const next = currentRole === 'admin' ? 'user' : 'admin';
    await adminApi.updateUser(id, { role: next });
    users.refetch();
  };
  const toggleActive = async (id: number, currentActive: boolean) => {
    await adminApi.updateUser(id, { is_active: !currentActive });
    users.refetch();
  };

  return (
    <div className="mx-auto max-w-5xl space-y-4 pb-16">
      <h1 className="text-2xl font-semibold">Users</h1>
      <Card>
        <CardContent className="p-0">
          {users.isLoading ? (
            <div className="p-6"><Loader2 className="h-4 w-4 animate-spin" /></div>
          ) : users.data?.items?.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/40 text-left text-xs text-muted-foreground">
                    <th className="px-2 py-2">ID</th>
                    <th className="px-2 py-2">Username</th>
                    <th className="px-2 py-2">Email</th>
                    <th className="px-2 py-2">Role</th>
                    <th className="px-2 py-2">Active</th>
                    <th className="px-2 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {users.data.items.map((u) => (
                    <tr key={u.id} className="border-b border-border last:border-0">
                      <td className="px-2 py-2 font-mono text-xs">{u.id}</td>
                      <td className="px-2 py-2">{u.username}</td>
                      <td className="px-2 py-2 text-xs text-muted-foreground">
                        {u.email ?? '—'}
                      </td>
                      <td className="px-2 py-2">{u.role}</td>
                      <td className="px-2 py-2">{u.is_active ? 'yes' : 'no'}</td>
                      <td className="px-2 py-2 text-right">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => toggleRole(u.id, u.role)}
                        >
                          Toggle role
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => toggleActive(u.id, u.is_active)}
                        >
                          Toggle active
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="p-6 text-sm text-muted-foreground">No users.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
