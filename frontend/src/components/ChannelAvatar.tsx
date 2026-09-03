import { useState } from 'react';

interface ChannelAvatarProps {
  src: string | null;
  title: string;
  className?: string;
}

/**
 * A channel/video thumbnail with a fallback: shows the image when a URL is
 * present and loads successfully, otherwise a placeholder with the title's
 * first letter — instead of rendering nothing (missing thumbnail_url) or a
 * broken-image icon (a URL that fails to load).
 */
export default function ChannelAvatar({ src, title, className }: ChannelAvatarProps) {
  const [failed, setFailed] = useState(false);

  if (!src || failed) {
    const initial = title.trim().charAt(0).toUpperCase() || '?';
    return (
      <div className={`channel-avatar-placeholder ${className || ''}`} title={title}>
        {initial}
      </div>
    );
  }

  return <img src={src} alt={title} className={className} onError={() => setFailed(true)} />;
}
