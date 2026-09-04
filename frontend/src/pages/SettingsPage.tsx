import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSettings, useUpdateSettings, useRescanShorts, useYouTubeAuthStart, useDeleteYouTubeAuth } from '../api/settings';
import { useApiKeys, useCreateApiKey, useDeleteApiKey } from '../api/apiKeys';
import { useSyncStatus, useStartSync, SyncStatus } from '../api/sync';
import { useToast } from '../context/ToastContext';
import { getErrorMessage } from '../utils/errors';
import '../styles/settings.css';

export default function SettingsPage() {
  const [searchParams] = useSearchParams();
  const [showNotification, setShowNotification] = useState(false);

  // Settings
  const { data: settings, isLoading: settingsLoading } = useSettings();
  const [backfillDays, setBackfillDays] = useState(0);
  const [backfillMinCount, setBackfillMinCount] = useState(0);
  const [syncIntervalMinutes, setSyncIntervalMinutes] = useState(0);
  const [backfillWorkerIntervalSeconds, setBackfillWorkerIntervalSeconds] = useState(0);
  const [updateLookbackDays, setUpdateLookbackDays] = useState(0);
  const [rssFallbackEnabled, setRssFallbackEnabled] = useState(true);
  const [strictShortsDetection, setStrictShortsDetection] = useState(false);
  const updateSettingsMutation = useUpdateSettings();
  const rescanShortsMutation = useRescanShorts();

  // YouTube
  const youtubeAuthStartMutation = useYouTubeAuthStart();
  const deleteYouTubeAuthMutation = useDeleteYouTubeAuth();

  // API Keys
  const { data: apiKeysData } = useApiKeys();
  const [keyLabel, setKeyLabel] = useState('');
  const [keyValue, setKeyValue] = useState('');
  const createApiKeyMutation = useCreateApiKey();
  const deleteApiKeyMutation = useDeleteApiKey();

  // Sync
  const { data: syncStatus } = useSyncStatus();
  const startSyncMutation = useStartSync();

  const { showError, showSuccess } = useToast();

  useEffect(() => {
    if (settings) {
      setBackfillDays(settings.backfill_days);
      setBackfillMinCount(settings.backfill_min_count);
      setSyncIntervalMinutes(settings.sync_interval_minutes);
      setBackfillWorkerIntervalSeconds(settings.backfill_worker_interval_seconds);
      setUpdateLookbackDays(settings.update_lookback_days);
      setRssFallbackEnabled(settings.rss_fallback_enabled);
      setStrictShortsDetection(settings.strict_shorts_detection);
    }
  }, [settings]);

  useEffect(() => {
    if (searchParams.get('youtube') === 'connected') {
      setShowNotification(true);
      const timer = setTimeout(() => setShowNotification(false), 3000);
      return () => clearTimeout(timer);
    }
  }, [searchParams]);

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await updateSettingsMutation.mutateAsync({
        backfill_days: backfillDays,
        backfill_min_count: backfillMinCount,
        sync_interval_minutes: syncIntervalMinutes,
        backfill_worker_interval_seconds: backfillWorkerIntervalSeconds,
        update_lookback_days: updateLookbackDays,
        rss_fallback_enabled: rssFallbackEnabled,
        strict_shorts_detection: strictShortsDetection,
      });
      showSuccess('Settings saved');
    } catch (err) {
      showError(getErrorMessage(err, 'Failed to save settings'));
    }
  };

  const handleRescanShorts = async () => {
    try {
      const result = await rescanShortsMutation.mutateAsync();
      showSuccess(
        result.checked === 0
          ? 'No unverified uploads from the last 7 days to rescan'
          : `Rescanned ${result.checked} upload${result.checked === 1 ? '' : 's'} — ${result.reclassified} reclassified`,
      );
    } catch (err) {
      showError(getErrorMessage(err, 'Failed to rescan uploads'));
    }
  };

  const handleYouTubeConnect = async () => {
    try {
      const result = await youtubeAuthStartMutation.mutateAsync();
      window.location.href = result.authorization_url;
    } catch (err) {
      showError(getErrorMessage(err, 'Failed to start YouTube connection'));
    }
  };

  const handleYouTubeDisconnect = async () => {
    try {
      await deleteYouTubeAuthMutation.mutateAsync();
    } catch (err) {
      showError(getErrorMessage(err, 'Failed to disconnect YouTube'));
    }
  };

  const handleAddApiKey = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createApiKeyMutation.mutateAsync({
        label: keyLabel,
        key_value: keyValue,
      });
      setKeyLabel('');
      setKeyValue('');
    } catch (err) {
      showError(getErrorMessage(err, 'Failed to add API key'));
    }
  };

  const handleDeleteApiKey = async (id: number) => {
    if (confirm('Delete this API key?')) {
      try {
        await deleteApiKeyMutation.mutateAsync(id);
      } catch (err) {
        showError(getErrorMessage(err, 'Failed to delete API key'));
      }
    }
  };

  const handleSync = async () => {
    try {
      await startSyncMutation.mutateAsync();
    } catch (err) {
      showError(getErrorMessage(err, 'Failed to start sync'));
    }
  };

  return (
    <div className="settings-page">
      <h1>Settings</h1>

      {showNotification && <div className="notification">YouTube connected successfully!</div>}

      {/* Global Settings */}
      <section className="settings-section">
        <h2>Global Settings</h2>
        {settingsLoading ? (
          <p>Loading...</p>
        ) : (
          <form onSubmit={handleSaveSettings}>
            <div>
              <label>Backfill Days</label>
              <input
                type="number"
                value={backfillDays}
                onChange={(e) => setBackfillDays(Number(e.target.value))}
              />
            </div>
            <div>
              <label>Backfill Min Count</label>
              <input
                type="number"
                value={backfillMinCount}
                onChange={(e) => setBackfillMinCount(Number(e.target.value))}
              />
            </div>
            <div>
              <label>Sync Interval (minutes)</label>
              <input
                type="number"
                min={1}
                value={syncIntervalMinutes}
                onChange={(e) => setSyncIntervalMinutes(Number(e.target.value))}
              />
            </div>
            <div>
              <label>Backfill Worker Interval (seconds)</label>
              <input
                type="number"
                min={10}
                value={backfillWorkerIntervalSeconds}
                onChange={(e) => setBackfillWorkerIntervalSeconds(Number(e.target.value))}
              />
            </div>
            <div>
              <label>Update Lookback (days)</label>
              <input
                type="number"
                min={1}
                value={updateLookbackDays}
                onChange={(e) => setUpdateLookbackDays(Number(e.target.value))}
              />
              <p className="setting-hint">
                On an incremental update, how far back to keep paging through a channel's uploads
                looking for new ones.
              </p>
            </div>
            <div className="strict-shorts-toggle">
              <label>
                <input
                  type="checkbox"
                  checked={rssFallbackEnabled}
                  onChange={(e) => setRssFallbackEnabled(e.target.checked)}
                />
                Allow RSS fallback when API quota is exhausted
              </label>
              <p className="setting-hint">
                When every API key is out of quota, fall back to RSS for updates (fewer uploads per
                channel, no Shorts/Live classification) instead of waiting for quota to reset.
                Channels updated this way are automatically re-checked via the API once quota is
                available again.
              </p>
            </div>
            <div className="strict-shorts-toggle">
              <label>
                <input
                  type="checkbox"
                  checked={strictShortsDetection}
                  onChange={(e) => setStrictShortsDetection(e.target.checked)}
                />
                Strict Shorts detection
              </label>
              <p className="setting-hint">
                For uploads 3 minutes or under, checks youtube.com directly to tell an actual Short from a
                merely-short video (the duration-only default can misclassify these). Uses no YouTube API
                quota, but adds one extra web request per such upload and relies on an unofficial, undocumented
                YouTube behavior.
              </p>
              {settings?.strict_shorts_detection && (
                <div className="rescan-shorts">
                  <button type="button" onClick={handleRescanShorts} disabled={rescanShortsMutation.isPending}>
                    {rescanShortsMutation.isPending ? 'Rescanning...' : 'Rescan last 7 days'}
                  </button>
                  <p className="setting-hint">
                    Re-checks uploads from the last 7 days that haven't been verified yet — lets you apply
                    strict detection to uploads fetched before you turned it on, without waiting for a fresh
                    sync.
                  </p>
                </div>
              )}
            </div>
            <button type="submit" disabled={updateSettingsMutation.isPending}>
              {updateSettingsMutation.isPending ? 'Saving...' : 'Save Settings'}
            </button>
          </form>
        )}
      </section>

      {/* YouTube Connection */}
      <section className="settings-section">
        <h2>YouTube Connection</h2>
        {settings?.youtube_connected ? (
          <div>
            <p>
              Connected as: <strong>{settings.youtube_channel_title}</strong>
            </p>
            <button onClick={handleYouTubeDisconnect}>Disconnect YouTube</button>
          </div>
        ) : (
          <button onClick={handleYouTubeConnect}>Connect YouTube</button>
        )}
      </section>

      {/* Sync */}
      <section className="settings-section">
        <h2>Sync</h2>
        <p>Last sync: {(syncStatus as SyncStatus | undefined)?.last_sync?.started_at ? new Date((syncStatus as SyncStatus)!.last_sync!.started_at).toLocaleString() : 'Never'}</p>
        <button onClick={handleSync} disabled={(syncStatus as SyncStatus | undefined)?.is_running}>
          {(syncStatus as SyncStatus | undefined)?.is_running ? 'Syncing...' : 'Sync Now'}
        </button>
      </section>

      {/* API Keys */}
      <section className="settings-section">
        <h2>API Keys</h2>
        <form onSubmit={handleAddApiKey} className="add-key-form">
          <input
            type="text"
            placeholder="Label"
            value={keyLabel}
            onChange={(e) => setKeyLabel(e.target.value)}
          />
          <input
            type="password"
            placeholder="Key value"
            value={keyValue}
            onChange={(e) => setKeyValue(e.target.value)}
          />
          <button type="submit">Add Key</button>
        </form>

        {apiKeysData && apiKeysData.length > 0 ? (
          <table className="api-keys-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Status</th>
                <th>Quota Resets</th>
                <th>Last Used</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {apiKeysData.map((key) => (
                <tr key={key.id}>
                  <td>{key.label}</td>
                  <td>{key.status}</td>
                  <td>{key.quota_resets_at ? new Date(key.quota_resets_at).toLocaleDateString() : '-'}</td>
                  <td>{key.last_used_at ? new Date(key.last_used_at).toLocaleString() : '-'}</td>
                  <td>
                    <button onClick={() => handleDeleteApiKey(key.id)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p>No API keys</p>
        )}
      </section>
    </div>
  );
}
