import { BackfillTask } from '../api/backfill';
import ChannelAvatar from './ChannelAvatar';
import '../styles/backfill-task-row.css';

interface BackfillTaskRowProps {
  task: BackfillTask;
  onRetry: (id: number) => void;
}

const STATUS_LABELS: Record<string, string> = {
  queued: 'Queued',
  in_progress: 'In Progress',
  paused_quota: 'Paused - Quota Exhausted',
  completed: 'Completed',
  failed: 'Failed',
};

export default function BackfillTaskRow({ task, onRetry }: BackfillTaskRowProps) {
  const progress = Math.min((task.fetched_count / task.target_min_count) * 100, 100);

  return (
    <div className="backfill-task-row">
      <div className="task-header">
        <ChannelAvatar src={task.channel.thumbnail_url} title={task.channel.title} className="task-thumb" />
        <div>
          <h3>{task.channel.title}</h3>
          <p className="status">{STATUS_LABELS[task.status]}</p>
        </div>
      </div>

      <div className="task-progress">
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${progress}%` }} />
        </div>
        <p className="progress-text">
          {task.fetched_count} / {task.target_min_count} videos
        </p>
      </div>

      {task.status === 'paused_quota' && (
        <p className="pause-note">The task will resume automatically when quota is available.</p>
      )}

      {task.status === 'failed' && task.last_error && (
        <div className="error-info">
          <p className="error">{task.last_error}</p>
          <button onClick={() => onRetry(task.id)}>Retry</button>
        </div>
      )}
    </div>
  );
}
