import { Link, Outlet, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useSyncStatus, SyncStatus } from '../api/sync';
import { logout } from '../api/auth';
import { useTheme } from '../hooks/useTheme';
import '../styles/layout.css';

export default function Layout() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: syncStatus } = useSyncStatus();
  const { theme, toggleTheme } = useTheme();

  const handleLogout = async () => {
    try {
      await logout();
    } catch (err) {
      console.error('Logout failed:', err);
    } finally {
      // Same reason as the login flow (see LoginPage): without this, a
      // stale cached "authenticated: true" would let ProtectedRoute wave
      // through a protected route for up to 5 minutes after logging out.
      await queryClient.invalidateQueries({ queryKey: ['auth', 'status'] });
      navigate('/login', { replace: true });
    }
  };

  const statusData = syncStatus as SyncStatus | undefined;

  return (
    <div className="layout">
      <nav className="sidebar">
        <div className="sidebar-header">
          <h1>Music Badger</h1>
        </div>
        <ul className="sidebar-menu">
          <li><Link to="/feed">Feed</Link></li>
          <li><Link to="/channels">Channels</Link></li>
          <li><Link to="/tags">Tags</Link></li>
          <li><Link to="/settings">Settings</Link></li>
          <li><Link to="/backfill">Backfill</Link></li>
        </ul>
        {statusData?.unacknowledged_unsubscribed_count ? (
          <div className="unsubscribe-banner">
            {statusData.unacknowledged_unsubscribed_count} channel(s) unsubscribed
          </div>
        ) : null}
        <div className="sidebar-footer">
          <button
            className="theme-toggle-btn"
            onClick={toggleTheme}
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          >
            {theme === 'dark' ? '☀️ Light mode' : '🌙 Dark mode'}
          </button>
          <button className="logout-btn" onClick={handleLogout}>Logout</button>
        </div>
      </nav>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
