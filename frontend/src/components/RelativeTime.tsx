import { relativeTimeInfo, formatDate, formatTime } from '../utils/dates';
import '../styles/relative-time.css';

interface RelativeTimeProps {
  iso: string;
  className?: string;
}

export default function RelativeTime({ iso, className }: RelativeTimeProps) {
  const { label } = relativeTimeInfo(iso);

  return (
    <span className={`relative-time${className ? ` ${className}` : ''}`}>
      {label}
      <span className="relative-time-tooltip">
        <span className="relative-time-tooltip-date">{formatDate(iso)}</span>
        <span className="relative-time-tooltip-sep" />
        <span className="relative-time-tooltip-time">{formatTime(iso)}</span>
      </span>
    </span>
  );
}
