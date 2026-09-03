import { useBackfillTasks, useRetryBackfillTask, BackfillTask } from '../api/backfill';
import { useToast } from '../context/ToastContext';
import { getErrorMessage } from '../utils/errors';
import BackfillTaskRow from '../components/BackfillTaskRow';
import '../styles/backfill.css';

export default function BackfillPage() {
  const { data: tasksData, isLoading } = useBackfillTasks(undefined, {
    refetchInterval: () => {
      // Poll every 5 seconds if any task is queued, in_progress, or paused_quota
      const tasks = tasksData as BackfillTask[] | undefined;
      const hasActiveTask = tasks?.some(
        (task) =>
          task.status === 'queued' ||
          task.status === 'in_progress' ||
          task.status === 'paused_quota',
      );
      return hasActiveTask ? 5000 : false;
    },
  });

  const retryMutation = useRetryBackfillTask();
  const { showError } = useToast();

  const handleRetry = async (id: number) => {
    try {
      await retryMutation.mutateAsync(id);
    } catch (err) {
      showError(getErrorMessage(err, 'Failed to retry backfill task'));
    }
  };

  // Calculate summary stats
  const tasks = tasksData as BackfillTask[] | undefined;
  const stats = {
    inProgress: tasks?.filter((t) => t.status === 'in_progress').length || 0,
    queued: tasks?.filter((t) => t.status === 'queued').length || 0,
    pausedQuota: tasks?.filter((t) => t.status === 'paused_quota').length || 0,
  };

  return (
    <div className="backfill-page">
      <h1>Backfill Progress</h1>

      {stats.inProgress > 0 || stats.queued > 0 || stats.pausedQuota > 0 ? (
        <div className="backfill-summary">
          {stats.inProgress > 0 && <span>{stats.inProgress} in progress</span>}
          {stats.queued > 0 && <span>{stats.queued} queued</span>}
          {stats.pausedQuota > 0 && <span>{stats.pausedQuota} paused (quota)</span>}
        </div>
      ) : null}

      {isLoading ? (
        <p>Loading...</p>
      ) : !tasks || tasks.length === 0 ? (
        <p>No backfill tasks</p>
      ) : (
        <div className="backfill-list">
          {tasks.map((task) => (
            <BackfillTaskRow
              key={task.id}
              task={task}
              onRetry={handleRetry}
            />
          ))}
        </div>
      )}
    </div>
  );
}
