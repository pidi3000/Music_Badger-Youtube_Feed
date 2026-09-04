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

// formatDate's dd/mm/yyyy plus a locale-formatted time, both in the
// viewer's local timezone.
export function formatDateTime(isoString: string): string {
  const d = parseUtc(isoString);
  return `${formatDate(isoString)} ${d.toLocaleTimeString()}`;
}
