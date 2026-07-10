import { Suspense, lazy, type ReactNode } from 'react';
import { Navigate, createBrowserRouter } from 'react-router-dom';
import { Layout } from './components/Layout';
import { PageLoader } from './components/ui/Loaders';

// Route-level code splitting: each page is its own chunk, loaded on demand.
const RegulationsPage = lazy(() => import('./pages/RegulationsPage'));
const RegulationDetailPage = lazy(() => import('./pages/RegulationDetailPage'));
const ImportPage = lazy(() => import('./pages/ImportPage'));
const JobsPage = lazy(() => import('./pages/JobsPage'));
const ReviewQueuePage = lazy(() => import('./pages/ReviewQueuePage'));
const FieldDetailPage = lazy(() => import('./pages/FieldDetailPage'));
const ConditionDetailPage = lazy(() => import('./pages/ConditionDetailPage'));
const HsReviewPage = lazy(() => import('./pages/HsReviewPage'));
const RelationshipsPage = lazy(() => import('./pages/RelationshipsPage'));
const WizardPage = lazy(() => import('./pages/WizardPage'));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'));

const withSuspense = (node: ReactNode) => <Suspense fallback={<PageLoader />}>{node}</Suspense>;

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/regulations" replace /> },
      { path: 'regulations', element: withSuspense(<RegulationsPage />) },
      { path: 'regulations/:id', element: withSuspense(<RegulationDetailPage />) },
      { path: 'import', element: withSuspense(<ImportPage />) },
      { path: 'jobs', element: withSuspense(<JobsPage />) },
      { path: 'review', element: withSuspense(<ReviewQueuePage />) },
      { path: 'review/field/:id', element: withSuspense(<FieldDetailPage />) },
      { path: 'review/condition/:id', element: withSuspense(<ConditionDetailPage />) },
      { path: 'review/hs-mapping', element: withSuspense(<HsReviewPage />) },
      { path: 'review/relationships/:id', element: withSuspense(<RelationshipsPage />) },
      { path: 'wizard', element: withSuspense(<WizardPage />) },
      { path: '*', element: withSuspense(<NotFoundPage />) },
    ],
  },
]);
