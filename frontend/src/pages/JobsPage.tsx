import { useState } from 'react';
import { useJobs, useStopJob, useStopAllJobs, Job, JobKind, JobState } from '../api/jobs';
import { useRetryBackfillTask } from '../api/backfill';
import { useToast } from '../context/ToastContext';
import { getErrorMessage } from '../utils/errors';
import JobRow from '../components/JobRow';
import '../styles/jobs.css';

const ACTIVE_STATUSES = new Set(['queued', 'in_progress', 'paused_quota', 'running', 'stopping']);

const KIND_FILTERS: { value: JobKind | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'update', label: 'Upload update' },
  { value: 'backfill', label: 'Upload backfill' },
  { value: 'import_subscriptions', label: 'Subscription update' },
];

const STATE_FILTERS: { value: JobState | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'queued', label: 'Queued' },
  { value: 'running', label: 'Running' },
  { value: 'done', label: 'Done' },
  { value: 'stopped', label: 'Stopped / Error' },
];

export default function JobsPage() {
  const [kindFilter, setKindFilter] = useState<JobKind | 'all'>('all');
  const [stateFilter, setStateFilter] = useState<JobState | 'all'>('all');

  const { data: jobsData, isLoading } = useJobs(
    {
      kind: kindFilter === 'all' ? undefined : kindFilter,
      state: stateFilter === 'all' ? undefined : stateFilter,
    },
    {
      refetchInterval: (query) => {
        // Poll every 5 seconds while anything is still active. Reads
        // query.state.data (the value TanStack Query passes in), not the
        // `jobsData` this hook call is about to return — refetchInterval
        // runs synchronously during this very useJobs() call, before that
        // destructuring assignment completes, so closing over `jobsData`
        // here hits its temporal dead zone.
        //
        // Never returns false: doing so when there's currently nothing
        // active stops polling for good until something else (a reload, a
        // filter change) triggers a fresh fetch — so a job that starts
        // *after* the page loaded with none active (e.g. adding a channel
        // in another tab, or the scheduled sync firing) would never show up
        // without a manual reload. A slower baseline poll while idle still
        // catches that.
        const jobs = query.state.data as Job[] | undefined;
        const hasActiveJob = jobs?.some((job) => ACTIVE_STATUSES.has(job.status));
        return hasActiveJob ? 5000 : 15000;
      },
    },
  );

  const retryMutation = useRetryBackfillTask();
  const stopMutation = useStopJob();
  const stopAllMutation = useStopAllJobs();
  const [stoppingJobId, setStoppingJobId] = useState<string | null>(null);
  const { showError, showSuccess } = useToast();

  const handleRetryBackfill = async (backfillTaskId: number) => {
    try {
      await retryMutation.mutateAsync(backfillTaskId);
    } catch (err) {
      showError(getErrorMessage(err, 'Failed to retry backfill task'));
    }
  };

  const handleStop = async (jobId: string) => {
    setStoppingJobId(jobId);
    try {
      await stopMutation.mutateAsync(jobId);
    } catch (err) {
      showError(getErrorMessage(err, 'Failed to stop job'));
    } finally {
      setStoppingJobId(null);
    }
  };

  const handleStopAll = async () => {
    // Stops every stoppable job site-wide, regardless of the kind/state
    // filters currently applied to this view — the confirm text says so
    // explicitly rather than quoting the (filtered) count shown above.
    if (!confirm("Stop every active and queued job — backfills, upload updates, and subscription syncs — across the whole app? This can't be undone.")) {
      return;
    }
    try {
      const result = await stopAllMutation.mutateAsync();
      const total = result.stopped + result.stopping;
      showSuccess(
        total === 0
          ? 'Nothing to stop'
          : `Stopped ${result.stopped} immediately, ${result.stopping} winding down`,
      );
    } catch (err) {
      showError(getErrorMessage(err, 'Failed to stop all jobs'));
    }
  };

  const jobs = jobsData as Job[] | undefined;
  const activeCount = jobs?.filter((j) => ACTIVE_STATUSES.has(j.status)).length || 0;

  return (
    <div className="jobs-page">
      <div className="jobs-header">
        <div>
          <h1>Jobs</h1>
          <p className="jobs-subtitle">Backfill, upload updates, and subscription imports.</p>
        </div>
        <button
          type="button"
          className="stop-all-btn"
          onClick={handleStopAll}
          disabled={stopAllMutation.isPending}
        >
          {stopAllMutation.isPending ? 'Stopping...' : 'Stop All Jobs'}
        </button>
      </div>

      <div className="jobs-filter-bar">
        {KIND_FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            className={`jobs-filter-btn${kindFilter === f.value ? ' active' : ''}`}
            onClick={() => setKindFilter(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="jobs-filter-bar">
        {STATE_FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            className={`jobs-filter-btn${stateFilter === f.value ? ' active' : ''}`}
            onClick={() => setStateFilter(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {activeCount > 0 && (
        <div className="jobs-summary">
          <span>{activeCount} active</span>
        </div>
      )}

      {isLoading ? (
        <p>Loading...</p>
      ) : !jobs || jobs.length === 0 ? (
        <p>No jobs match this filter</p>
      ) : (
        <div className="jobs-list">
          {jobs.map((job) => (
            <JobRow
              key={job.id}
              job={job}
              onRetryBackfill={handleRetryBackfill}
              onStop={handleStop}
              isStopping={stoppingJobId === job.id}
            />
          ))}
        </div>
      )}
    </div>
  );
}
