import { useState } from 'react';
import { useChannels, useCreateChannel, useDeleteChannel, useUpdateChannel, useAckUnsubscribe, Channel } from '../api/channels';
import { useTags } from '../api/tags';
import ChannelRow from '../components/ChannelRow';
import AddChannelModal from '../components/AddChannelModal';
import '../styles/channels.css';

export default function ChannelsPage() {
  const [showAddModal, setShowAddModal] = useState(false);
  const { data: channelsData, isLoading } = useChannels();
  const { data: tagsData } = useTags();

  const channels = channelsData as Channel[] | undefined;
  const createChannelMutation = useCreateChannel();
  const deleteChannelMutation = useDeleteChannel();
  const updateChannelMutation = useUpdateChannel();
  const ackUnsubscribeMutation = useAckUnsubscribe();

  const handleAddChannel = async (channelLink: string, tagIds: number[]) => {
    try {
      await createChannelMutation.mutateAsync({
        channel_link: channelLink,
        tag_ids: tagIds.length > 0 ? tagIds : undefined,
      });
      setShowAddModal(false);
    } catch (err) {
      console.error('Failed to add channel:', err);
    }
  };

  const handleDeleteChannel = async (id: number) => {
    if (confirm('Are you sure?')) {
      try {
        await deleteChannelMutation.mutateAsync(id);
      } catch (err) {
        console.error('Failed to delete channel:', err);
      }
    }
  };

  const handleUpdateChannel = async (id: number, tagIds: number[], fetchMethod: string | null) => {
    try {
      await updateChannelMutation.mutateAsync({
        id,
        payload: {
          tag_ids: tagIds,
          upload_fetch_method: (fetchMethod === 'null' ? null : fetchMethod) as 'api' | 'rss' | null,
        },
      });
    } catch (err) {
      console.error('Failed to update channel:', err);
    }
  };

  const handleAckUnsubscribe = async (id: number) => {
    try {
      await ackUnsubscribeMutation.mutateAsync(id);
    } catch (err) {
      console.error('Failed to acknowledge unsubscribe:', err);
    }
  };

  return (
    <div className="channels-page">
      <div className="channels-header">
        <h1>Channels</h1>
        <button className="btn-primary" onClick={() => setShowAddModal(true)}>
          Add Channel
        </button>
      </div>

      {showAddModal && (
        <AddChannelModal onClose={() => setShowAddModal(false)} onSubmit={handleAddChannel} tags={tagsData || []} />
      )}

      {isLoading ? (
        <p>Loading...</p>
      ) : !channels || channels.length === 0 ? (
        <p>No channels yet</p>
      ) : (
        <div className="channels-grid">
          {channels.map((channel) => (
            <ChannelRow
              key={channel.id}
              channel={channel}
              allTags={tagsData || []}
              onDelete={handleDeleteChannel}
              onUpdate={handleUpdateChannel}
              onAckUnsubscribe={handleAckUnsubscribe}
            />
          ))}
        </div>
      )}
    </div>
  );
}
