import { useJobs, Job } from '../api/jobs';
import { useRetryBackfillTask } from '../api/backfill';
import { useToast } from '../context/ToastContext';
import { getErrorMessage } from '../utils/errors';
import JobRow from '../components/JobRow';
import '../styles/jobs.css';

const ACTIVE_STATUSES = new Set(['queued', 'in_progress', 'paused_quota', 'running']);

export default function JobsPage() {
  const { data: jobsData, isLoading } = useJobs({
    refetchInterval: (query) => {
      // Poll every 5 seconds while anything is still active. Reads
      // query.state.data (the value TanStack Query passes in), not the
      // `jobsData` this hook call is about to return — refetchInterval
      // runs synchronously during this very useJobs() call, before that
      // destructuring assignment completes, so closing over `jobsData`
      // here hits its temporal dead zone.
      const jobs = query.state.data as Job[] | undefined;
      const hasActiveJob = jobs?.some((job) => ACTIVE_STATUSES.has(job.status));
      return hasActiveJob ? 5000 : false;
    },
  });

  const retryMutation = useRetryBackfillTask();
  const { showError } = useToast();

  const handleRetryBackfill = async (backfillTaskId: number) => {
    try {
      await retryMutation.mutateAsync(backfillTaskId);
    } catch (err) {
      showError(getErrorMessage(err, 'Failed to retry backfill task'));
    }
  };

  const jobs = jobsData as Job[] | undefined;
  const activeCount = jobs?.filter((j) => ACTIVE_STATUSES.has(j.status)).length || 0;

  return (
    <div className="jobs-page">
      <h1>Jobs</h1>
      <p className="jobs-subtitle">Backfill, upload syncs, and subscription imports.</p>

      {activeCount > 0 && (
        <div className="jobs-summary">
          <span>{activeCount} active</span>
        </div>
      )}

      {isLoading ? (
        <p>Loading...</p>
      ) : !jobs || jobs.length === 0 ? (
        <p>No jobs yet</p>
      ) : (
        <div className="jobs-list">
          {jobs.map((job) => (
            <JobRow key={job.id} job={job} onRetryBackfill={handleRetryBackfill} />
          ))}
        </div>
      )}
    </div>
  );
}
