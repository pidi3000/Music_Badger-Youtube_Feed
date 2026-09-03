import { useState } from 'react';
import { Channel } from '../api/channels';
import { Tag } from '../api/tags';
import TagChip from './TagChip';
import '../styles/channel-row.css';

interface ChannelRowProps {
  channel: Channel;
  allTags: Tag[];
  onDelete: (id: number) => void;
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

export default function ChannelRow({
  channel,
  allTags,
  onDelete,
  onUpdate,
  onAckUnsubscribe,
}: ChannelRowProps) {
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
          {channel.thumbnail_url && (
            <img src={channel.thumbnail_url} alt={channel.title} className="channel-thumb" />
          )}
          <div>
            <h3>{channel.title}</h3>
            {channel.handle && <p className="handle">@{channel.handle}</p>}
          </div>
          <span className="source-badge">{channel.source}</span>
          <div
            className="status-dot"
            style={{ backgroundColor: BACKFILL_STATUS_COLORS[channel.backfill_status] }}
            title={channel.backfill_status}
          />
        </div>

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
            <button onClick={() => onDelete(channel.id)}>Delete</button>
          </>
        )}
      </div>
    </div>
  );
}
