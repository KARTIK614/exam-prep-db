import { createBrowserRouter, Navigate } from 'react-router-dom';

import { App } from '@/App';
import { Layout } from '@/components/Layout';
import { ProtectedRoute, PublicOnlyRoute } from '@/components/ProtectedRoute';
import Analytics from '@/pages/Analytics';
import Bookmarks from '@/pages/Bookmarks';
import Dashboard from '@/pages/Dashboard';
import ErrorLog from '@/pages/ErrorLog';
import ForgotPassword from '@/pages/ForgotPassword';
import Landing from '@/pages/Landing';
import Login from '@/pages/Login';
import NotFound from '@/pages/NotFound';
import Profile from '@/pages/Profile';
import ResetPassword from '@/pages/ResetPassword';
import Review from '@/pages/Review';
import Search from '@/pages/Search';
import Signup from '@/pages/Signup';
import TakeTest from '@/pages/TakeTest';
import TestResults from '@/pages/TestResults';
import TestSetup from '@/pages/TestSetup';
import AdminDashboard from '@/pages/admin/AdminDashboard';
import AdminDuplicates from '@/pages/admin/AdminDuplicates';
import AdminFlags from '@/pages/admin/AdminFlags';
import AdminQuestions from '@/pages/admin/AdminQuestions';
import AdminReview from '@/pages/admin/AdminReview';
import AdminSynthesize from '@/pages/admin/AdminSynthesize';
import AdminUploads from '@/pages/admin/AdminUploads';
import AdminUsers from '@/pages/admin/AdminUsers';

/**
 * Application route tree — expanded in Phase 9 to cover all top-level
 * feature pages plus the admin subtree.
 *
 * Structure:
 *   <App>
 *     <PublicOnlyRoute>          — /login, /signup, /forgot-*, /reset-*
 *     <ProtectedRoute>           — auth-gated shell
 *       <Layout>
 *         /dashboard             — feature-parity dashboard
 *         /test/new              — test setup form
 *         /test/:id              — TakeTest (killer feature)
 *         /test/:id/results      — results
 *         /analytics
 *         /errors
 *         /review                — SR queue
 *         /bookmarks
 *         /search
 *         /profile
 *     <ProtectedRoute requireAdmin>
 *       <Layout>
 *         /admin, /admin/questions, /admin/flags, /admin/review,
 *         /admin/duplicates, /admin/uploads, /admin/synthesize,
 *         /admin/users
 *     *                          — 404
 */
export const router = createBrowserRouter([
  {
    element: <App />,
    children: [
      // Public landing at `/` — Landing handles the "already logged in" redirect
      // itself so we don't need PublicOnlyRoute (which would 302 to /dashboard).
      { path: '/', element: <Landing /> },

      {
        element: <PublicOnlyRoute />,
        children: [
          { path: '/login', element: <Login /> },
          { path: '/signup', element: <Signup /> },
          { path: '/forgot-password', element: <ForgotPassword /> },
          { path: '/reset-password', element: <ResetPassword /> },
          { path: '/reset-password/:token', element: <ResetPassword /> },
        ],
      },

      // Authenticated routes — shared shell. `/` is handled above as the
      // public Landing (which itself redirects to /dashboard if authed).
      {
        element: <ProtectedRoute />,
        children: [
          {
            element: <Layout />,
            children: [
              { path: '/home', element: <Navigate to="/dashboard" replace /> },
              { path: '/dashboard', element: <Dashboard /> },
              { path: '/test/new', element: <TestSetup /> },
              { path: '/test/:id', element: <TakeTest /> },
              { path: '/test/:id/results', element: <TestResults /> },
              { path: '/analytics', element: <Analytics /> },
              { path: '/errors', element: <ErrorLog /> },
              { path: '/review', element: <Review /> },
              { path: '/bookmarks', element: <Bookmarks /> },
              { path: '/search', element: <Search /> },
              { path: '/profile', element: <Profile /> },
            ],
          },
        ],
      },

      // Admin subtree.
      {
        element: <ProtectedRoute requireAdmin />,
        children: [
          {
            path: '/admin',
            element: <Layout />,
            children: [
              { index: true, element: <AdminDashboard /> },
              { path: 'questions', element: <AdminQuestions /> },
              { path: 'flags', element: <AdminFlags /> },
              { path: 'review', element: <AdminReview /> },
              { path: 'duplicates', element: <AdminDuplicates /> },
              { path: 'uploads', element: <AdminUploads /> },
              { path: 'synthesize', element: <AdminSynthesize /> },
              { path: 'users', element: <AdminUsers /> },
            ],
          },
        ],
      },

      { path: '*', element: <NotFound /> },
    ],
  },
]);
