import type { ComponentType } from "react";
import type { ViewName } from "../types";
import { IconBookmark, IconChat, IconInfo, IconPlant } from "./Icons";

interface SidebarProps {
  view: ViewName;
  onNavigate: (view: ViewName) => void;
  onClose: () => void;
}

const NAV: { id: ViewName; label: string; icon: ComponentType }[] = [
  { id: "chat", label: "Chat", icon: IconChat },
  { id: "herbs", label: "Herb Library", icon: IconPlant },
  { id: "saved", label: "Saved Answers", icon: IconBookmark },
  { id: "about", label: "About This Tool", icon: IconInfo },
];

export function Sidebar({ view, onNavigate, onClose }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar__logo">
        <img src="/symbol.png" alt="Charaka AI" />
      </div>

      <nav className="sidebar__nav">
        {NAV.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              className={`nav-item ${view === item.id ? "nav-item--active" : ""}`}
              onClick={() => {
                onNavigate(item.id);
                onClose();
              }}
            >
              <Icon />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="sidebar__footer">
        <div className="sidebar__chip">
          Not a diagnosis tool — always know when to see a doctor.
        </div>
      </div>
    </aside>
  );
}