import { Upload } from '../api/feed';
import { youtubeChannelUrl } from '../utils/youtube';
import { formatDateTime } from '../utils/dates';
import ChannelAvatar from './ChannelAvatar';
import '../styles/upload-card.css';

interface UploadCardProps {
  upload: Upload;
}

const VIDEO_TYPE_LABELS: Record<Upload['video_type'], string> = {
  video: 'Video',
  short: 'Short',
  live: 'Live',
};

export default function UploadCard({ upload }: UploadCardProps) {
  const videoUrl = `https://www.youtube.com/watch?v=${upload.youtube_video_id}`;
  const channelUrl = youtubeChannelUrl(upload.channel);
  const publishedAt = formatDateTime(upload.published_at);

  const handleClick = () => {
    window.open(videoUrl, '_blank');
  };

  return (
    <div className="upload-card" onClick={handleClick}>
      <div className="upload-thumbnail">
        {upload.thumbnail_url ? (
          <img src={upload.thumbnail_url} alt={upload.title} />
        ) : (
          <div className="placeholder">No image</div>
        )}
        <span className={`video-type-badge video-type-${upload.video_type}`}>
          {VIDEO_TYPE_LABELS[upload.video_type]}
        </span>
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
          <span className="date">{publishedAt}</span>
          {upload.fetched_via === 'rss' && <span className="badge">RSS</span>}
        </div>
      </div>
    </div>
  );
}
