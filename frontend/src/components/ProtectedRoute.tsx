import { ReactNode } from 'react';
import { useAuthStatus } from '../api/auth';
import LoginPage from '../pages/LoginPage';

interface ProtectedRouteProps {
  children: ReactNode;
}

export default function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { data, isLoading } = useAuthStatus();

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <p>Loading...</p>
      </div>
    );
  }

  if (!data?.authenticated) {
    return <LoginPage />;
  }

  return <>{children}</>;
}
