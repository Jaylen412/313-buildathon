import type { ViewName } from "../App";

const TOP_ITEMS: { key: ViewName; label: string }[] = [
  { key: "home", label: "Home" },
  { key: "map", label: "Map" },
  { key: "residents", label: "Residents" },
  { key: "insights", label: "Insights" },
];

interface SidebarProps {
  active: ViewName;
  onChange: (view: ViewName) => void;
}

export function Sidebar({ active, onChange }: SidebarProps) {
  return (
    <nav className="sidebar">
      <div className="sidebar-group">
        {TOP_ITEMS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={active === item.key ? "sidebar-btn active" : "sidebar-btn"}
            onClick={() => onChange(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="sidebar-bottom">
        <button
          type="button"
          className={active === "settings" ? "sidebar-btn active" : "sidebar-btn"}
          onClick={() => onChange("settings")}
        >
          Settings
        </button>
      </div>
    </nav>
  );
}
