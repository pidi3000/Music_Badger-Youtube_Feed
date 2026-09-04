import { createBrowserRouter, Navigate } from 'react-router-dom';
import LoginPage from './pages/LoginPage';
import FeedPage from './pages/FeedPage';
import ChannelsPage from './pages/ChannelsPage';
import TagsPage from './pages/TagsPage';
import SettingsPage from './pages/SettingsPage';
import JobsPage from './pages/JobsPage';
import Layout from './components/Layout';
import ProtectedRoute from './components/ProtectedRoute';

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/',
    element: <ProtectedRoute><Layout /></ProtectedRoute>,
    children: [
      {
        index: true,
        element: <Navigate to="/feed" replace />,
      },
      {
        path: 'feed',
        element: <FeedPage />,
      },
      {
        path: 'channels',
        element: <ChannelsPage />,
      },
      {
        path: 'tags',
        element: <TagsPage />,
      },
      {
        path: 'settings',
        element: <SettingsPage />,
      },
      {
        path: 'jobs',
        element: <JobsPage />,
      },
    ],
  },
]);
