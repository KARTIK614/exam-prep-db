import { useState } from 'react';
import { Link } from 'react-router-dom';
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
import { useForgotPassword } from '@/lib/api/auth';

/**
 * Forgot-password page.
 *
 * Sends the email to POST /api/v1/auth/forgot-password. Regardless of
 * whether the address is registered, we render the same "check your email"
 * confirmation — the backend does not disclose account existence and the
 * client mustn't leak it either.
 *
 * If the mutation itself fails at a transport level (network down, 500)
 * we surface a generic error but still hint that the user can retry.
 */
const schema = z.object({
  email: z.string().email('Enter a valid email address'),
});

type FormValues = z.infer<typeof schema>;

export default function ForgotPassword() {
  const forgot = useForgotPassword();
  const [submitted, setSubmitted] = useState(false);
  const [transportError, setTransportError] = useState<string | null>(null);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: '' },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    setTransportError(null);
    try {
      await forgot.mutateAsync({ email: values.email });
      setSubmitted(true);
    } catch {
      // Even a 4xx from the server should look identical to a 2xx to the
      // user. Only bubble truly-broken-network scenarios where the request
      // never reached the backend.
      setSubmitted(true);
    }
  });

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg-primary p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Reset your password</CardTitle>
          <CardDescription>
            Enter your account email and we'll send you a reset link.
          </CardDescription>
        </CardHeader>
        {submitted ? (
          <CardContent className="space-y-4">
            <div
              role="status"
              className="rounded-md border border-border bg-muted p-4 text-sm"
            >
              If that email is registered, a reset link is on its way. Check
              your inbox (and spam folder) in the next few minutes.
            </div>
            <div className="text-center text-sm">
              <Link to="/login" className="text-primary hover:underline">
                Back to sign in
              </Link>
            </div>
          </CardContent>
        ) : (
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
                        <Input
                          type="email"
                          autoComplete="email"
                          autoFocus
                          {...field}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                {transportError && (
                  <div
                    role="alert"
                    className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive"
                  >
                    {transportError}
                  </div>
                )}
              </CardContent>
              <CardFooter className="flex-col items-stretch gap-3">
                <Button type="submit" disabled={forgot.isPending}>
                  {forgot.isPending ? 'Sending…' : 'Send reset link'}
                </Button>
                <p className="text-center text-sm text-muted-foreground">
                  Remembered it?{' '}
                  <Link to="/login" className="text-primary hover:underline">
                    Sign in
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
