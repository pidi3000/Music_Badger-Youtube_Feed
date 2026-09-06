import { useEffect, useState } from 'react';
import { parseUtc } from '../utils/dates';

// Ticks once a second so a currently-live upload's duration overlay reads
// as "current" rather than a number that's already stale from the last
// classification check (which only runs every few minutes — see
// AppSettings.live_recheck_interval_minutes).
export function useElapsedSeconds(startIso: string | null): number | null {
  const [elapsed, setElapsed] = useState<number | null>(
    startIso ? Math.max(0, Math.floor((Date.now() - parseUtc(startIso).getTime()) / 1000)) : null,
  );

  useEffect(() => {
    if (!startIso) {
      setElapsed(null);
      return;
    }
    const startMs = parseUtc(startIso).getTime();
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - startMs) / 1000)));
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [startIso]);

  return elapsed;
}
