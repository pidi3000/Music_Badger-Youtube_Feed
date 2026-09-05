import { Channel } from '../api/channels';
import { Tag } from '../api/tags';
import { youtubeChannelUrl } from '../utils/youtube';
import { formatDate, formatDateTime } from '../utils/dates';
import ChannelAvatar from './ChannelAvatar';
import '../styles/channel-row.css';

interface ChannelRowProps {
  channel: Channel;
  allTags: Tag[];
  onDelete: () => void;
  onUpdate: (id: number, tagIds: number[]) => void;
  onAckUnsubscribe: (id: number) => void;
}

const BACKFILL_STATUS_COLORS: Record<string, string> = {
  not_started: '#d3d3d3',
  queued: '#fbbf24',
  in_progress: '#60a5fa',
  paused_quota: '#f87171',
  completed: '#34d399',
  failed: '#ef4444',
};

function formatChannelStats(channel: Channel): string {
  const parts = [`${channel.upload_count} upload${channel.upload_count === 1 ? '' : 's'}`];
  if (channel.oldest_upload_at) {
    parts.push(`oldest ${formatDate(channel.oldest_upload_at)}`);
  }
  parts.push(channel.last_synced_at ? `updated ${formatDateTime(channel.last_synced_at)}` : 'never updated');
  if (channel.subscribed_at) {
    parts.push(`subscribed ${formatDate(channel.subscribed_at)}`);
  }
  return parts.join(' · ');
}

export default function ChannelRow({ channel, allTags, onDelete, onUpdate, onAckUnsubscribe }: ChannelRowProps) {
  const selectedTagIds = new Set(channel.tags.map((t) => t.id));

  // Applied immediately on click, no Edit/Save flow — clicking a chip is
  // the whole interaction, so tagging a long channel list stays fast.
  const handleToggleTag = (tagId: number) => {
    const nextTagIds = selectedTagIds.has(tagId)
      ? [...selectedTagIds].filter((id) => id !== tagId)
      : [...selectedTagIds, tagId];
    onUpdate(channel.id, nextTagIds);
  };

  return (
    <div className="channel-row">
      <div className="channel-main">
        <div className="channel-header">
          <ChannelAvatar src={channel.thumbnail_url} title={channel.title} className="channel-thumb" />
          <div>
            <h3>
              <a href={youtubeChannelUrl(channel)} target="_blank" rel="noopener noreferrer">
                {channel.title}
              </a>
            </h3>
            {channel.handle && <p className="handle">@{channel.handle}</p>}
          </div>
          <span className="source-badge">{channel.source}</span>
          {channel.subscription_status === 'unsubscribed' && (
            <span className="unsubscribed-badge" title={channel.unsubscribed_at ? `Unsubscribed ${formatDate(channel.unsubscribed_at)}` : undefined}>
              Unsubscribed
            </span>
          )}
          <div
            className="status-dot"
            style={{ backgroundColor: BACKFILL_STATUS_COLORS[channel.backfill_status] }}
            title={channel.backfill_status}
          />
        </div>

        <p className="channel-stats">{formatChannelStats(channel)}</p>

        {channel.subscription_status === 'unsubscribed' && !channel.unsubscribed_ack && (
          <div className="unsubscribe-warning">
            <span>Unsubscribed on YouTube</span>
            <button onClick={() => onAckUnsubscribe(channel.id)}>Dismiss</button>
          </div>
        )}

        {allTags.length > 0 && (
          <div className="tags-toggle">
            {allTags.map((tag) => {
              const active = selectedTagIds.has(tag.id);
              return (
                <button
                  key={tag.id}
                  type="button"
                  className={`tag-toggle-chip${active ? ' active' : ''}`}
                  style={
                    active
                      ? { backgroundColor: tag.color, borderColor: tag.color }
                      : { borderColor: tag.color, color: tag.color }
                  }
                  onClick={() => handleToggleTag(tag.id)}
                  aria-pressed={active}
                >
                  {tag.name}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="channel-actions">
        <button onClick={onDelete}>Delete</button>
      </div>
    </div>
  );
}
