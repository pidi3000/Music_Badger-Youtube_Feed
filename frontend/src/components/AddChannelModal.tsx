import { useState } from 'react';
import { Tag } from '../api/tags';
import '../styles/modal.css';

interface AddChannelModalProps {
  onClose: () => void;
  onSubmit: (channelLink: string, tagIds: number[]) => void;
  tags: Tag[];
}

export default function AddChannelModal({ onClose, onSubmit, tags }: AddChannelModalProps) {
  const [channelLink, setChannelLink] = useState('');
  const [selectedTags, setSelectedTags] = useState<number[]>([]);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!channelLink.trim()) {
      setError('Please enter a channel link');
      return;
    }

    try {
      await onSubmit(channelLink, selectedTags);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add channel');
    }
  };

  const handleToggleTag = (tagId: number) => {
    setSelectedTags((prev) =>
      prev.includes(tagId) ? prev.filter((id) => id !== tagId) : [...prev, tagId],
    );
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <h2>Add Channel</h2>
        <form onSubmit={handleSubmit}>
          <input
            type="text"
            placeholder="Paste channel URL, video URL, or handle"
            value={channelLink}
            onChange={(e) => setChannelLink(e.target.value)}
            autoFocus
          />

          <div>
            <label>Tags (optional)</label>
            <div className="tag-checkboxes">
              {tags.map((tag) => (
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
          </div>

          {error && <p className="error">{error}</p>}

          <div className="modal-actions">
            <button type="submit">Add</button>
            <button type="button" onClick={onClose}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
