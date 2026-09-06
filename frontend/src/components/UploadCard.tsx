import { Upload } from '../api/feed';
import { youtubeChannelUrl } from '../utils/youtube';
import { formatDateTime } from '../utils/dates';
import { formatDuration } from '../utils/duration';
import ChannelAvatar from './ChannelAvatar';
import RelativeTime from './RelativeTime';
import '../styles/upload-card.css';

interface UploadCardProps {
  upload: Upload;
}

// No entry for "unknown" — not yet classified, so no type badge is shown
// at all rather than guessing or labeling it "Unknown".
const VIDEO_TYPE_LABELS: Partial<Record<Upload['video_type'], string>> = {
  video: 'Video',
  short: 'Short',
  live: 'Live',
};

export default function UploadCard({ upload }: UploadCardProps) {
  const videoUrl =
    upload.video_type === 'short'
      ? `https://www.youtube.com/shorts/${upload.youtube_video_id}`
      : `https://www.youtube.com/watch?v=${upload.youtube_video_id}`;
  const channelUrl = youtubeChannelUrl(upload.channel);

  const handleClick = () => {
    window.open(videoUrl, '_blank');
  };

  const typeLabel = VIDEO_TYPE_LABELS[upload.video_type];
  const isUpcoming = upload.video_type === 'live' && upload.live_status === 'upcoming';
  const isActiveLive = upload.video_type === 'live' && upload.live_status === 'live';
  // A "live" upload only has a real, final duration once its broadcast has
  // ended — while it's upcoming/live there's nothing to show yet.
  const hasDuration =
    upload.duration_seconds != null &&
    upload.duration_seconds > 0 &&
    (upload.video_type !== 'live' || upload.live_status === 'ended');

  return (
    <div className="upload-card" onClick={handleClick}>
      <div className="upload-thumbnail">
        {upload.thumbnail_url ? (
          <img src={upload.thumbnail_url} alt={upload.title} />
        ) : (
          <div className="placeholder">No image</div>
        )}
        {typeLabel && <span className={`video-type-badge video-type-${upload.video_type}`}>{typeLabel}</span>}
        {isActiveLive && (
          <span className="corner-badge live-now-badge">
            <span className="live-dot" />
            Live
          </span>
        )}
        {isUpcoming && <span className="corner-badge upcoming-badge">Upcoming</span>}
        {hasDuration && <span className="corner-badge duration-badge">{formatDuration(upload.duration_seconds!)}</span>}
      </div>
      <div className="upload-info">
        <h3>{upload.title}</h3>
        <a
          href={channelUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="channel-info"
          onClick={(e) => e.stopPropagation()}
        >
          <ChannelAvatar src={upload.channel.thumbnail_url} title={upload.channel.title} className="channel-thumb" />
          <span>{upload.channel.title}</span>
        </a>
        <div className="meta">
          {isUpcoming && upload.scheduled_start_at ? (
            <span className="date">Scheduled for {formatDateTime(upload.scheduled_start_at)}</span>
          ) : (
            <RelativeTime iso={upload.published_at} className="date" />
          )}
          {upload.fetched_via === 'rss' && <span className="badge">RSS</span>}
        </div>
      </div>
    </div>
  );
}
