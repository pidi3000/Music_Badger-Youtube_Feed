import { Outlet, useNavigate } from 'react-router-dom';
import { useSyncStatus, SyncStatus } from '../api/sync';
import { logout } from '../api/auth';
import '../styles/layout.css';

export default function Layout() {
  const navigate = useNavigate();
  const { data: syncStatus } = useSyncStatus();

  const handleLogout = async () => {
    try {
      await logout();
      navigate('/login');
    } catch (err) {
      console.error('Logout failed:', err);
      navigate('/login');
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
          <li><a href="/feed">Feed</a></li>
          <li><a href="/channels">Channels</a></li>
          <li><a href="/tags">Tags</a></li>
          <li><a href="/settings">Settings</a></li>
          <li><a href="/backfill">Backfill</a></li>
        </ul>
        {statusData?.unacknowledged_unsubscribed_count ? (
          <div className="unsubscribe-banner">
            {statusData.unacknowledged_unsubscribed_count} channel(s) unsubscribed
          </div>
        ) : null}
        <button className="logout-btn" onClick={handleLogout}>Logout</button>
      </nav>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
