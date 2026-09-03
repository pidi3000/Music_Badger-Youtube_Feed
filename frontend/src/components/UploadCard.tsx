import { Link } from 'react-router-dom';
import { Upload } from '../api/feed';
import ChannelAvatar from './ChannelAvatar';
import '../styles/upload-card.css';

interface UploadCardProps {
  upload: Upload;
}

export default function UploadCard({ upload }: UploadCardProps) {
  const videoUrl = `https://www.youtube.com/watch?v=${upload.youtube_video_id}`;
  const publishedDate = new Date(upload.published_at).toLocaleDateString();

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
      </div>
      <div className="upload-info">
        <h3>{upload.title}</h3>
        <Link
          to={`/channels?highlight=${upload.channel.id}`}
          className="channel-info"
          onClick={(e) => e.stopPropagation()}
        >
          <ChannelAvatar src={upload.channel.thumbnail_url} title={upload.channel.title} className="channel-thumb" />
          <span>{upload.channel.title}</span>
        </Link>
        <div className="meta">
          <span className="date">{publishedDate}</span>
          {upload.fetched_via === 'rss' && <span className="badge">RSS</span>}
        </div>
      </div>
    </div>
  );
}
