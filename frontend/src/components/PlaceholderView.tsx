interface PlaceholderViewProps {
  title: string;
  description: string;
}

export function PlaceholderView({ title, description }: PlaceholderViewProps) {
  return (
    <div className="view-placeholder">
      <h2>{title}</h2>
      <p className="muted">{description}</p>
    </div>
  );
}
