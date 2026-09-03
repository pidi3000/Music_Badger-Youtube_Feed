import { useState } from 'react';
import { useTags, useCreateTag, useUpdateTag, useDeleteTag } from '../api/tags';
import { randomTagColor } from '../utils/color';
import { useToast } from '../context/ToastContext';
import { getErrorMessage } from '../utils/errors';
import '../styles/tags.css';

export default function TagsPage() {
  const [newTagName, setNewTagName] = useState('');
  const [newTagColor, setNewTagColor] = useState<string>(() => randomTagColor());
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [editColor, setEditColor] = useState('');

  const { data: tagsData, isLoading } = useTags();
  const createTagMutation = useCreateTag();
  const updateTagMutation = useUpdateTag();
  const deleteTagMutation = useDeleteTag();
  const { showError } = useToast();

  const handleAddTag = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTagName.trim()) return;

    try {
      await createTagMutation.mutateAsync({
        name: newTagName,
        color: newTagColor,
      });
      setNewTagName('');
      setNewTagColor(randomTagColor());
    } catch (err) {
      showError(getErrorMessage(err, 'Failed to create tag'));
    }
  };

  const handleStartEdit = (id: number, name: string, color: string) => {
    setEditingId(id);
    setEditName(name);
    setEditColor(color);
  };

  const handleSaveEdit = async (id: number) => {
    try {
      await updateTagMutation.mutateAsync({
        id,
        payload: {
          name: editName,
          color: editColor,
        },
      });
      setEditingId(null);
    } catch (err) {
      showError(getErrorMessage(err, 'Failed to update tag'));
    }
  };

  const handleDelete = async (id: number) => {
    if (confirm('Delete this tag?')) {
      try {
        await deleteTagMutation.mutateAsync(id);
      } catch (err) {
        showError(getErrorMessage(err, 'Failed to delete tag'));
      }
    }
  };

  return (
    <div className="tags-page">
      <h1>Tags</h1>

      <form className="add-tag-form" onSubmit={handleAddTag}>
        <input
          type="text"
          placeholder="Tag name"
          value={newTagName}
          onChange={(e) => setNewTagName(e.target.value)}
        />
        <input
          type="color"
          value={newTagColor}
          onChange={(e) => setNewTagColor(e.target.value)}
        />
        <button type="submit">Add Tag</button>
      </form>

      {isLoading ? (
        <p>Loading...</p>
      ) : tagsData?.length === 0 ? (
        <p>No tags yet</p>
      ) : (
        <div className="tags-list">
          {tagsData?.map((tag) =>
            editingId === tag.id ? (
              <div key={tag.id} className="tag-row editing">
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                />
                <input
                  type="color"
                  value={editColor}
                  onChange={(e) => setEditColor(e.target.value)}
                />
                <button onClick={() => handleSaveEdit(tag.id)}>Save</button>
                <button onClick={() => setEditingId(null)}>Cancel</button>
              </div>
            ) : (
              <div key={tag.id} className="tag-row">
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div
                    style={{
                      backgroundColor: tag.color,
                      width: '20px',
                      height: '20px',
                      borderRadius: '4px',
                    }}
                  />
                  <span>{tag.name}</span>
                </div>
                <div>
                  <button onClick={() => handleStartEdit(tag.id, tag.name, tag.color)}>Edit</button>
                  <button onClick={() => handleDelete(tag.id)}>Delete</button>
                </div>
              </div>
            ),
          )}
        </div>
      )}
    </div>
  );
}
