// The backend sends naive UTC timestamps (e.g. "2026-09-04T12:34:56.789012"
// — no "Z"/offset, see backend/app/models.py's "stored UTC-naive, interpreted
// as UTC" convention). The JS Date parser treats a timezone-less ISO string
// as *local* time, not UTC, so parsing it directly would silently shift
// every timestamp by the viewer's UTC offset. Appending "Z" here makes sure
// it's parsed as the UTC instant it actually is; everything downstream
// (Date's local getters, toLocaleTimeString) then converts it to the
// viewer's own system timezone.
function parseUtc(isoString: string): Date {
  const hasTimezone = /[Zz]|[+-]\d{2}:?\d{2}$/.test(isoString);
  return new Date(hasTimezone ? isoString : `${isoString}Z`);
}

// dd/mm/yyyy, in the viewer's local timezone — not locale-dependent, since
// Date's plain getters (getDate/getMonth/getFullYear) already report the
// local calendar date and toLocaleDateString()'s format varies by browser
// locale (e.g. mm/dd/yyyy under en-US).
export function formatDate(isoString: string): string {
  const d = parseUtc(isoString);
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  return `${dd}/${mm}/${d.getFullYear()}`;
}

// Locale-formatted time only (viewer's local timezone) — pairs with
// formatDate for callers that render the date and time separately (e.g.
// RelativeTime's hover tooltip).
export function formatTime(isoString: string): string {
  return parseUtc(isoString).toLocaleTimeString();
}

// formatDate's dd/mm/yyyy plus a locale-formatted time, both in the
// viewer's local timezone.
export function formatDateTime(isoString: string): string {
  return `${formatDate(isoString)} ${formatTime(isoString)}`;
}

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;
const MONTH = 30 * DAY;
const YEAR = 365 * DAY;

export interface RelativeTimeInfo {
  label: string;
  // A stable key shared by every timestamp in the same day/week/month/year
  // bucket, used to group the Feed page's uploads list under one separator
  // per bucket. Null for anything under 24h old — those never get a
  // separator (see FeedPage).
  bucketKey: string | null;
}

// "40 minutes ago" / "6 hours ago" / "1 day ago" / "2 weeks ago" /
// "4 months ago" / "3 years ago" — day granularity through the first week,
// then week/month/year, each floor()'d (so "1 week ago" covers day 7
// through day 13, etc.) rather than calendar-exact.
export function relativeTimeInfo(isoString: string, now: Date = new Date()): RelativeTimeInfo {
  const then = parseUtc(isoString);
  const diffMs = Math.max(now.getTime() - then.getTime(), 0);

  if (diffMs < MINUTE) return { label: 'just now', bucketKey: null };
  if (diffMs < HOUR) {
    const n = Math.floor(diffMs / MINUTE);
    return { label: `${n} minute${n === 1 ? '' : 's'} ago`, bucketKey: null };
  }
  if (diffMs < DAY) {
    const n = Math.floor(diffMs / HOUR);
    return { label: `${n} hour${n === 1 ? '' : 's'} ago`, bucketKey: null };
  }
  if (diffMs < WEEK) {
    const n = Math.floor(diffMs / DAY);
    return { label: `${n} day${n === 1 ? '' : 's'} ago`, bucketKey: `day:${n}` };
  }
  if (diffMs < MONTH) {
    const n = Math.floor(diffMs / WEEK);
    return { label: `${n} week${n === 1 ? '' : 's'} ago`, bucketKey: `week:${n}` };
  }
  if (diffMs < YEAR) {
    const n = Math.floor(diffMs / MONTH);
    return { label: `${n} month${n === 1 ? '' : 's'} ago`, bucketKey: `month:${n}` };
  }
  const n = Math.floor(diffMs / YEAR);
  return { label: `${n} year${n === 1 ? '' : 's'} ago`, bucketKey: `year:${n}` };
}

export function formatRelativeTime(isoString: string, now: Date = new Date()): string {
  return relativeTimeInfo(isoString, now).label;
}
