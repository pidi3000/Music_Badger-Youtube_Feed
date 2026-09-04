import { Job } from '../api/jobs';
import ChannelAvatar from './ChannelAvatar';
import '../styles/job-row.css';

interface JobRowProps {
  job: Job;
  onRetryBackfill: (backfillTaskId: number) => void;
}

const KIND_LABELS: Record<Job['kind'], string> = {
  update: 'Upload update',
  backfill: 'Upload backfill',
  import_subscriptions: 'Subscription update',
};

const STATUS_LABELS: Record<string, string> = {
  queued: 'Queued',
  in_progress: 'In Progress',
  paused_quota: 'Paused - Quota Exhausted',
  completed: 'Completed',
  failed: 'Failed',
  running: 'Running',
  success: 'Success',
  error: 'Error',
};

const STATUS_COLORS: Record<string, string> = {
  queued: '#fbbf24',
  in_progress: '#60a5fa',
  running: '#60a5fa',
  paused_quota: '#f87171',
  completed: '#34d399',
  success: '#34d399',
  failed: '#ef4444',
  error: '#ef4444',
};

export default function JobRow({ job, onRetryBackfill }: JobRowProps) {
  const canRetry = job.kind === 'backfill' && job.status === 'failed' && job.backfill_task_id !== null;
  const progress =
    job.kind === 'backfill' && job.target_min_count
      ? Math.min(((job.fetched_count ?? 0) / job.target_min_count) * 100, 100)
      : null;

  return (
    <div className="job-row">
      <div className="job-header">
        {job.channel ? (
          <ChannelAvatar src={job.channel.thumbnail_url} title={job.channel.title} className="job-thumb" />
        ) : (
          <div className="job-thumb-placeholder">↻</div>
        )}
        <div>
          <h3>{job.channel ? job.channel.title : 'All subscriptions'}</h3>
          <p className="job-kind">{KIND_LABELS[job.kind]}</p>
        </div>
        <span
          className="job-status-badge"
          style={{ backgroundColor: STATUS_COLORS[job.status] || '#d3d3d3' }}
        >
          {STATUS_LABELS[job.status] || job.status}
        </span>
      </div>

      {progress !== null && (
        <div className="job-progress">
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${progress}%` }} />
          </div>
          <p className="progress-text">
            {job.fetched_count} / {job.target_min_count} uploads
          </p>
        </div>
      )}

      {!progress && job.detail && <p className="job-detail">{job.detail}</p>}

      {job.status === 'paused_quota' && (
        <p className="pause-note">Will resume automatically when quota is available.</p>
      )}

      {job.error && (
        <div className="error-info">
          <p className="error">{job.error}</p>
          {canRetry && <button onClick={() => onRetryBackfill(job.backfill_task_id as number)}>Retry</button>}
        </div>
      )}
    </div>
  );
}
