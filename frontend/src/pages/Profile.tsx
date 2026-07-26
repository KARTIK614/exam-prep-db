import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { useMe, useUpdateMe } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/types';

/**
 * Profile page.
 *
 * Renders the currently-authenticated user's info (from `useMe`) and
 * offers a single form that can update the email address AND/OR change
 * the password. The backend requires `current_password` whenever
 * `new_password` is set — we mirror that as cross-field validation so
 * the user gets the error without a network round-trip.
 *
 * Cache: `useUpdateMe` writes the response back into `['me']`, so the
 * displayed fields refresh without an explicit refetch.
 */

// Cross-field validation: when new_password is set, current_password
// must be too. Also enforce match on confirm.
const schema = z
  .object({
    email: z.string().email('Enter a valid email address'),
    currentPassword: z.string().optional().default(''),
    newPassword: z.string().optional().default(''),
    confirmPassword: z.string().optional().default(''),
  })
  .superRefine((v, ctx) => {
    if (v.newPassword && v.newPassword.length > 0) {
      if (v.newPassword.length < 8) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['newPassword'],
          message: 'Password must be at least 8 characters',
        });
      }
      if (!v.currentPassword) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['currentPassword'],
          message: 'Current password is required to set a new one',
        });
      }
      if (v.newPassword !== v.confirmPassword) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['confirmPassword'],
          message: 'Passwords do not match',
        });
      }
    }
  });

type FormValues = z.infer<typeof schema>;

export default function Profile() {
  const meQuery = useMe();
  const updateMe = useUpdateMe();
  const [formError, setFormError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      email: '',
      currentPassword: '',
      newPassword: '',
      confirmPassword: '',
    },
  });

  // Seed the form once `me` arrives. `form` is a stable RHF handle so
  // omitting it from deps is safe and idiomatic.
  useEffect(() => {
    if (meQuery.data) {
      form.reset({
        email: meQuery.data.email ?? '',
        currentPassword: '',
        newPassword: '',
        confirmPassword: '',
      });
    }
  }, [meQuery.data, form]);

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    setSuccessMsg(null);

    // Build a minimal PATCH body — only include fields the user actually
    // changed. This keeps the API's optional-field semantics intact.
    const body: {
      email?: string;
      current_password?: string;
      new_password?: string;
    } = {};

    if (values.email && values.email !== (meQuery.data?.email ?? '')) {
      body.email = values.email;
    }
    if (values.newPassword) {
      body.new_password = values.newPassword;
      body.current_password = values.currentPassword;
    }

    if (Object.keys(body).length === 0) {
      setFormError('Nothing to update.');
      return;
    }

    try {
      await updateMe.mutateAsync(body);
      setSuccessMsg('Profile updated.');
      form.reset({
        email: values.email,
        currentPassword: '',
        newPassword: '',
        confirmPassword: '',
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setFormError('Current password is incorrect.');
      } else if (err instanceof ApiError && err.status >= 400 && err.status < 500) {
        setFormError(err.message || 'Could not update profile.');
      } else {
        setFormError('Something went wrong. Please try again.');
      }
    }
  });

  if (meQuery.isPending) {
    return <div className="text-muted-foreground">Loading profile…</div>;
  }
  if (meQuery.isError || !meQuery.data) {
    return (
      <div role="alert" className="text-destructive">
        Could not load your profile.
      </div>
    );
  }

  const me = meQuery.data;

  return (
    <div className="mx-auto w-full max-w-2xl space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>
            Signed in as <span className="font-medium">{me.username}</span>
            {me.role !== 'user' && (
              <span className="ml-2 rounded bg-muted px-2 py-0.5 text-xs uppercase tracking-wide">
                {me.role}
              </span>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div>
            <span className="text-muted-foreground">Member since:</span>{' '}
            {me.created_at ?? '—'}
          </div>
          <div>
            <span className="text-muted-foreground">Last login:</span>{' '}
            {me.last_login ?? '—'}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Update details</CardTitle>
          <CardDescription>
            Change your email address, your password, or both.
          </CardDescription>
        </CardHeader>
        <Form {...form}>
          <form onSubmit={onSubmit} noValidate>
            <CardContent className="space-y-4">
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Email</FormLabel>
                    <FormControl>
                      <Input type="email" autoComplete="email" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="border-t pt-4">
                <p className="mb-3 text-sm font-medium">
                  Change password (optional)
                </p>
                <div className="space-y-4">
                  <FormField
                    control={form.control}
                    name="currentPassword"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Current password</FormLabel>
                        <FormControl>
                          <Input
                            type="password"
                            autoComplete="current-password"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="newPassword"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>New password</FormLabel>
                        <FormControl>
                          <Input
                            type="password"
                            autoComplete="new-password"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="confirmPassword"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Confirm new password</FormLabel>
                        <FormControl>
                          <Input
                            type="password"
                            autoComplete="new-password"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              </div>

              {formError && (
                <div
                  role="alert"
                  className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive"
                >
                  {formError}
                </div>
              )}
              {successMsg && (
                <div
                  role="status"
                  className="rounded-md border border-success/50 bg-success/10 p-3 text-sm"
                >
                  {successMsg}
                </div>
              )}
            </CardContent>
            <CardFooter>
              <Button type="submit" disabled={updateMe.isPending}>
                {updateMe.isPending ? 'Saving…' : 'Save changes'}
              </Button>
            </CardFooter>
          </form>
        </Form>
      </Card>
    </div>
  );
}
