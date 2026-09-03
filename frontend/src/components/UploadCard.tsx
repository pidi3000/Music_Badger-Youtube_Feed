import { Upload } from '../api/feed';
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
        <div className="channel-info">
          {upload.channel.thumbnail_url && (
            <img src={upload.channel.thumbnail_url} alt={upload.channel.title} className="channel-thumb" />
          )}
          <span>{upload.channel.title}</span>
        </div>
        <div className="meta">
          <span className="date">{publishedDate}</span>
          {upload.fetched_via === 'rss' && <span className="badge">RSS</span>}
        </div>
      </div>
    </div>
  );
}
