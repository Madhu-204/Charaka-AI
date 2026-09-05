import type { ComponentType } from "react";
import type { ViewName } from "../types";
import { IconBook, IconBookmark, IconChat, IconInfo, IconLeaf } from "./Icons";

interface SidebarProps {
  view: ViewName;
  onNavigate: (view: ViewName) => void;
  onClose: () => void;
}

const NAV: { id: ViewName; label: string; icon: ComponentType }[] = [
  { id: "chat", label: "Chat", icon: IconChat },
  { id: "herbs", label: "Herb Library", icon: IconBook },
  { id: "saved", label: "Saved Answers", icon: IconBookmark },
  { id: "about", label: "About This Tool", icon: IconInfo },
];

function Artwork() {
  return (
    <svg width="96" height="64" viewBox="0 0 96 64" fill="none" aria-hidden>
      <g stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
        <path d="M18 50c10-24 20-34 40-34-2 18-10 26-40 34Z" fill="currentColor" opacity="0.16" />
        <path d="M38 12 42 24" />
        <path d="M42 24l8-6" />
        <path d="M42 24l-6 8" />
        <path d="M50 16 54 26" />
        <path d="M54 26l6-3" />
        <path d="M70 20c2 8 0 14-4 22" />
        <circle cx="30" cy="48" r="4" opacity="0.5" />
        <circle cx="62" cy="42" r="3" opacity="0.5" />
      </g>
    </svg>
  );
}

export function Sidebar({ view, onNavigate, onClose }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar__logo">
        <IconLeaf />
        <span>CHARAKA&nbsp;AI</span>
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
        <div className="sidebar__art">
          <Artwork />
        </div>
        <div className="sidebar__chip">
          Not a diagnosis tool — always know when to see a doctor.
        </div>
      </div>
    </aside>
  );
}