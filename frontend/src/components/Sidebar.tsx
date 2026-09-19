import type { ViewName } from "../views";

const TOP_ITEMS: { key: ViewName; label: string; icon: string }[] = [
  { key: "home", label: "Home", icon: "home" },
  { key: "map", label: "Map", icon: "map" },
  { key: "neighborhoods", label: "Neighborhoods", icon: "family_group" },
  { key: "insights", label: "Insights", icon: "insights" },
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
            style={{ fontFamily: 'Inter' }}
            type="button"
            className={active === item.key ? "sidebar-btn active" : "sidebar-btn"}
            onClick={() => onChange(item.key)}
          >
            <span className="material-symbols-outlined sidebar-icon" aria-hidden="true">
              {item.icon}
            </span>
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
          <span className="material-symbols-outlined sidebar-icon" aria-hidden="true">
            settings
          </span>
          Settings
        </button>
      </div>
    </nav>
  );
}
