import { useState } from 'react';
import { Channel } from '../api/channels';
import { Tag } from '../api/tags';
import { youtubeChannelUrl } from '../utils/youtube';
import TagChip from './TagChip';
import ChannelAvatar from './ChannelAvatar';
import '../styles/channel-row.css';

interface ChannelRowProps {
  channel: Channel;
  allTags: Tag[];
  onDelete: () => void;
  onUpdate: (id: number, tagIds: number[], fetchMethod: string | null) => void;
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
    parts.push(`oldest ${new Date(channel.oldest_upload_at).toLocaleDateString()}`);
  }
  parts.push(
    channel.last_synced_at ? `updated ${new Date(channel.last_synced_at).toLocaleString()}` : 'never updated',
  );
  if (channel.subscribed_at) {
    parts.push(`subscribed ${new Date(channel.subscribed_at).toLocaleDateString()}`);
  }
  return parts.join(' · ');
}

export default function ChannelRow({ channel, allTags, onDelete, onUpdate, onAckUnsubscribe }: ChannelRowProps) {
  const [showEdit, setShowEdit] = useState(false);
  const [selectedTags, setSelectedTags] = useState<number[]>(channel.tags.map((t) => t.id));
  const [fetchMethod, setFetchMethod] = useState<string | null>(channel.upload_fetch_method);

  const handleSave = () => {
    onUpdate(channel.id, selectedTags, fetchMethod);
    setShowEdit(false);
  };

  const handleToggleTag = (tagId: number) => {
    setSelectedTags((prev) =>
      prev.includes(tagId) ? prev.filter((id) => id !== tagId) : [...prev, tagId],
    );
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

        {!showEdit ? (
          <>
            <div className="tags-display">
              {channel.tags.map((tag) => (
                <TagChip key={tag.id} tag={tag} />
              ))}
            </div>
            <p className="fetch-method">Fetch: {channel.effective_fetch_method}</p>
          </>
        ) : (
          <>
            <div className="tags-edit">
              {allTags.map((tag) => (
                <label key={tag.id}>
                  <input
                    type="checkbox"
                    checked={selectedTags.includes(tag.id)}
                    onChange={() => handleToggleTag(tag.id)}
                  />
                  {tag.name}
                </label>
              ))}
            </div>
            <select value={fetchMethod || 'null'} onChange={(e) => setFetchMethod(e.target.value === 'null' ? null : (e.target.value as 'api' | 'rss'))}>
              <option value="null">Use default</option>
              <option value="api">API</option>
              <option value="rss">RSS</option>
            </select>
          </>
        )}
      </div>

      <div className="channel-actions">
        {showEdit ? (
          <>
            <button onClick={handleSave}>Save</button>
            <button onClick={() => setShowEdit(false)}>Cancel</button>
          </>
        ) : (
          <>
            <button onClick={() => setShowEdit(true)}>Edit</button>
            <button onClick={onDelete}>Delete</button>
          </>
        )}
      </div>
    </div>
  );
}
