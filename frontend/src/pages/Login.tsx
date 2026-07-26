import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
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
import { useLogin } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/types';

/**
 * Login page.
 *
 * Behaviour:
 *   - Accepts either username OR email in the identifier field — backend
 *     handler tries both (see backend/src/api/auth.rs::login).
 *   - On success, tokens land in the auth store (see `useLogin`) and we
 *     navigate to `?next=` if it's a safe relative path, else /dashboard.
 *   - On failure, we render a generic "invalid credentials" message to
 *     avoid leaking whether the account exists. The `code` from the API
 *     is inspected only to distinguish 4xx from 5xx (which gets a
 *     different message).
 */

const schema = z.object({
  usernameOrEmail: z.string().min(1, 'Enter your username or email'),
  password: z.string().min(1, 'Enter your password'),
});

type FormValues = z.infer<typeof schema>;

/** Only allow same-origin relative paths — never redirect off-site. */
function safeNext(raw: string | null): string {
  if (!raw) return '/dashboard';
  if (!raw.startsWith('/')) return '/dashboard';
  if (raw.startsWith('//')) return '/dashboard';
  return raw;
}

export default function Login() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const login = useLogin();
  const [formError, setFormError] = useState<string | null>(null);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { usernameOrEmail: '', password: '' },
  });

  // Clear the "invalid credentials" banner as soon as the user starts
  // editing either field. `watch()` in a dep array is the RHF-idiomatic
  // way to react to value changes without wiring up a subscription.
  const usernameOrEmail = form.watch('usernameOrEmail');
  const password = form.watch('password');
  useEffect(() => {
    setFormError(null);
  }, [usernameOrEmail, password]);

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    try {
      await login.mutateAsync({
        username_or_email: values.usernameOrEmail,
        password: values.password,
      });
      navigate(safeNext(params.get('next')), { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status >= 400 && err.status < 500) {
        setFormError('Invalid username or password.');
      } else {
        setFormError('Something went wrong. Please try again.');
      }
    }
  });

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg-primary p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Sign in</CardTitle>
          <CardDescription>
            Welcome back. Enter your details to continue.
          </CardDescription>
        </CardHeader>
        <Form {...form}>
          <form onSubmit={onSubmit} noValidate>
            <CardContent className="space-y-4">
              <FormField
                control={form.control}
                name="usernameOrEmail"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Username or email</FormLabel>
                    <FormControl>
                      <Input
                        autoComplete="username"
                        autoFocus
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Password</FormLabel>
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
              {formError && (
                <div
                  role="alert"
                  className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive"
                >
                  {formError}
                </div>
              )}
              <div className="text-right text-sm">
                <Link
                  to="/forgot-password"
                  className="text-primary hover:underline"
                >
                  Forgot password?
                </Link>
              </div>
            </CardContent>
            <CardFooter className="flex-col items-stretch gap-3">
              <Button type="submit" disabled={login.isPending}>
                {login.isPending ? 'Signing in…' : 'Sign in'}
              </Button>
              <p className="text-center text-sm text-muted-foreground">
                No account?{' '}
                <Link to="/signup" className="text-primary hover:underline">
                  Create one
                </Link>
              </p>
            </CardFooter>
          </form>
        </Form>
      </Card>
    </div>
  );
}
