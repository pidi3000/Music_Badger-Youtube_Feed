import { Tag } from '../api/tags';
import '../styles/tag-chip.css';

interface TagChipProps {
  tag: Tag;
}

export default function TagChip({ tag }: TagChipProps) {
  return (
    <span className="tag-chip" style={{ backgroundColor: tag.color }}>
      {tag.name}
    </span>
  );
}
