import { useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
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
import { useResetPassword } from '@/lib/api/auth';
import { ApiError } from '@/lib/api/types';

/**
 * Reset-password page.
 *
 * Accepts the token either as a path parameter (`/reset-password/:token`)
 * or as a `?token=` query string, to match whichever URL format the email
 * template ends up using. Path parameter takes precedence.
 */
const schema = z
  .object({
    password: z
      .string()
      .min(8, 'Password must be at least 8 characters')
      .max(256, 'Password too long'),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, {
    message: 'Passwords do not match',
    path: ['confirm'],
  });

type FormValues = z.infer<typeof schema>;

export default function ResetPassword() {
  const navigate = useNavigate();
  const params = useParams<{ token?: string }>();
  const [search] = useSearchParams();
  const token = params.token ?? search.get('token') ?? '';

  const reset = useResetPassword();
  const [formError, setFormError] = useState<string | null>(null);
  const [succeeded, setSucceeded] = useState(false);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { password: '', confirm: '' },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    if (!token) {
      setFormError('Reset link is missing a token.');
      return;
    }
    try {
      await reset.mutateAsync({ token, body: { new_password: values.password } });
      setSucceeded(true);
      // Redirect after a short beat so the user sees the confirmation.
      setTimeout(() => navigate('/login', { replace: true }), 1500);
    } catch (err) {
      if (err instanceof ApiError && err.status >= 400 && err.status < 500) {
        setFormError('This reset link is invalid or has expired.');
      } else {
        setFormError('Something went wrong. Please try again.');
      }
    }
  });

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg-primary p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Set a new password</CardTitle>
          <CardDescription>
            Pick a strong password you haven't used before.
          </CardDescription>
        </CardHeader>
        {succeeded ? (
          <CardContent className="space-y-4">
            <div
              role="status"
              className="rounded-md border border-success/50 bg-success/10 p-3 text-sm"
            >
              Password reset. Redirecting you to sign in…
            </div>
          </CardContent>
        ) : (
          <Form {...form}>
            <form onSubmit={onSubmit} noValidate>
              <CardContent className="space-y-4">
                <FormField
                  control={form.control}
                  name="password"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>New password</FormLabel>
                      <FormControl>
                        <Input
                          type="password"
                          autoComplete="new-password"
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
                  name="confirm"
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
                {formError && (
                  <div
                    role="alert"
                    className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive"
                  >
                    {formError}
                  </div>
                )}
              </CardContent>
              <CardFooter className="flex-col items-stretch gap-3">
                <Button type="submit" disabled={reset.isPending}>
                  {reset.isPending ? 'Resetting…' : 'Reset password'}
                </Button>
                <p className="text-center text-sm text-muted-foreground">
                  <Link to="/login" className="text-primary hover:underline">
                    Back to sign in
                  </Link>
                </p>
              </CardFooter>
            </form>
          </Form>
        )}
      </Card>
    </div>
  );
}
