import { Link, Navigate } from 'react-router-dom';
import {
  BarChart3,
  BookOpenCheck,
  Clock,
  Keyboard,
  Layers,
  Smartphone,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useAuthStore } from '@/stores/authStore';

/**
 * Landing — public marketing page at `/`.
 *
 * Redirects authenticated users straight to /dashboard. Everyone else sees
 * hero, features, sample question preview, testimonial (placeholder — needs
 * permission before Sujit's name ships), and footer.
 *
 * Mobile-first, dark-mode-aware via CSS variables from `globals.css`.
 */
export default function Landing() {
  const { hydrated, user } = useAuthStore();

  // Auth store rehydrates from localStorage synchronously in this app; still
  // guard against the first render race by waiting for `hydrated`.
  if (hydrated && user) {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <div className="min-h-screen bg-bg-primary text-text-primary">
      {/* Top bar */}
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <Link to="/" className="text-lg font-semibold tracking-tight">
            Exam Prep Platform
          </Link>
          <div className="flex items-center gap-2">
            <Link to="/login">
              <Button variant="ghost" size="sm">Sign in</Button>
            </Link>
            <Link to="/signup">
              <Button size="sm">Sign up free</Button>
            </Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-6xl px-4 py-12 sm:py-20 text-center">
          <h1 className="text-3xl sm:text-5xl font-bold tracking-tight">
            Exam prep that actually feels like the exam.
          </h1>
          <p className="mt-4 text-base sm:text-lg text-muted-foreground max-w-2xl mx-auto">
            MCQ practice with the real exam UI — TCS-iON palette, keyboard
            shortcuts, timer, negative marking. 3,700+ curated questions from
            past-year papers across GATE, SSC CGL, RPSC, BCI and more.
          </p>
          <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link to="/signup">
              <Button size="lg">Sign up free</Button>
            </Link>
            <Link to="/login">
              <Button size="lg" variant="ghost">
                I already have an account
              </Button>
            </Link>
          </div>
          <p className="mt-4 text-xs text-muted-foreground">
            Free forever · No credit card · One-click exam bundles
          </p>
        </div>
      </section>

      {/* Features */}
      <section className="mx-auto max-w-6xl px-4 py-12 sm:py-16">
        <h2 className="text-2xl font-semibold mb-6 text-center">
          Everything you need to prep like it's exam day
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Feature
            icon={<Keyboard className="h-5 w-5" />}
            title="Real exam UI"
            body="TCS-iON question palette. Keyboard shortcuts. Per-question timer. Mark for review. Everything matches the actual test day."
          />
          <Feature
            icon={<Layers className="h-5 w-5" />}
            title="One-click exam bundles"
            body="Preconfigured mocks for GATE CS, SSC CGL, RPSC Programmer, BCI, UGC NET, and more. Skip the setup — start studying."
          />
          <Feature
            icon={<BookOpenCheck className="h-5 w-5" />}
            title="3,700+ curated questions"
            body="Past-year papers plus AI-verified explanations. Filter by exam, year, difficulty, or topic. Bookmark what matters."
          />
          <Feature
            icon={<Clock className="h-5 w-5" />}
            title="Spaced repetition"
            body="Leitner-5 boxes on your wrong answers. Review just what's due — no more re-doing what you already know."
          />
          <Feature
            icon={<BarChart3 className="h-5 w-5" />}
            title="Mastery + weakness heatmap"
            body="See exactly which topics need work. Consistency score, next-weak-topic picker, pacing charts. Actionable dashboards."
          />
          <Feature
            icon={<Smartphone className="h-5 w-5" />}
            title="Works on your phone"
            body="Study in transit. Bottom nav, touch-friendly palette. Dark mode. Same features as desktop, sized for a 375px screen."
          />
        </div>
      </section>

      {/* Sample question preview */}
      <section className="border-t border-border bg-bg-secondary">
        <div className="mx-auto max-w-4xl px-4 py-12 sm:py-16">
          <h2 className="text-2xl font-semibold mb-2 text-center">
            This is what a question looks like.
          </h2>
          <p className="text-sm text-muted-foreground text-center mb-6">
            No mid-test answer reveals. See correct answers only after final submit.
          </p>
          <div className="mx-auto max-w-2xl rounded-lg border border-border bg-bg-primary p-4 sm:p-6">
            <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
              <span>Q 7 / 25</span>
              <span>·</span>
              <span>DBMS &amp; SQL</span>
              <span className="ml-auto rounded-full border border-border px-2 py-0.5">
                Medium
              </span>
            </div>
            <div className="text-sm sm:text-base font-medium mb-4">
              Which normalization form eliminates transitive dependencies?
            </div>
            <ul className="space-y-2 text-sm">
              {['1NF', '2NF', '3NF', 'BCNF'].map((opt, i) => (
                <li
                  key={opt}
                  className="rounded-md border border-border bg-bg-secondary px-3 py-2 cursor-not-allowed opacity-90"
                >
                  <span className="mr-2 font-mono text-xs text-muted-foreground">
                    {String.fromCharCode(65 + i)}
                  </span>
                  {opt}
                </li>
              ))}
            </ul>
            <div className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
              <span>Timer: 00:42</span>
              <span className="flex items-center gap-2">
                <kbd className="rounded border border-border px-1.5 py-0.5">A</kbd>
                <kbd className="rounded border border-border px-1.5 py-0.5">B</kbd>
                <kbd className="rounded border border-border px-1.5 py-0.5">C</kbd>
                <kbd className="rounded border border-border px-1.5 py-0.5">D</kbd>
                to select
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* Testimonial — TODO: verify permission before shipping Sujit's name */}
      <section className="mx-auto max-w-4xl px-4 py-12 sm:py-16">
        <blockquote className="text-center">
          <p className="text-lg sm:text-xl italic text-text-primary">
            &ldquo;Baar baar subject select karne ki jhanjhat nahi. Ek click me
            SSC CGL mock, aur seedha exam feel.&rdquo;
          </p>
          <footer className="mt-4 text-sm text-muted-foreground">
            {/* TODO: verify permission before shipping full name in production */}
            — Sujit P., government-exam aspirant
          </footer>
        </blockquote>
      </section>

      {/* Final CTA */}
      <section className="border-t border-border bg-bg-secondary">
        <div className="mx-auto max-w-4xl px-4 py-12 sm:py-16 text-center">
          <h2 className="text-2xl sm:text-3xl font-semibold">
            Ready to start?
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Sign up in under 30 seconds. No credit card. Free forever.
          </p>
          <div className="mt-6">
            <Link to="/signup">
              <Button size="lg">Create your free account</Button>
            </Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border">
        <div className="mx-auto max-w-6xl px-4 py-8 flex flex-col sm:flex-row items-center justify-between gap-3 text-sm text-muted-foreground">
          <div>© {new Date().getFullYear()} Exam Prep Platform</div>
          <nav className="flex gap-4">
            <a href="#about" className="hover:text-text-primary">
              About
            </a>
            <a
              href="mailto:hello@example.com"
              className="hover:text-text-primary"
            >
              Contact
            </a>
            <a href="#privacy" className="hover:text-text-primary">
              Privacy
            </a>
          </nav>
        </div>
      </footer>
    </div>
  );
}

function Feature({
  icon,
  title,
  body,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-bg-secondary p-4">
      <div className="mb-2 inline-flex h-8 w-8 items-center justify-center rounded-md bg-primary/10 text-primary">
        {icon}
      </div>
      <h3 className="text-base font-semibold">{title}</h3>
      <p className="mt-1 text-sm text-muted-foreground">{body}</p>
    </div>
  );
}
