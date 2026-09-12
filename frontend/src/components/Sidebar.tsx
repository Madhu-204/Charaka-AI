import { useCallback, useEffect, useState } from "react";
import type { ComponentType } from "react";
import type { ConversationSummary, ViewName } from "../types";
import { deleteConversation, fetchConversations } from "../api";
import {
  IconBookmark,
  IconChat,
  IconFolder,
  IconInfo,
  IconPlant,
  IconPlus,
  IconTrash,
} from "./Icons";

interface SidebarProps {
  view: ViewName;
  onNavigate: (view: ViewName) => void;
  onClose: () => void;
  activeConversationId: string | null;
  conversationRefresh: number;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
}

const NAV: { id: ViewName; label: string; icon: ComponentType }[] = [
  { id: "chat", label: "Chat", icon: IconChat },
  { id: "explore", label: "Explore Corpus", icon: IconFolder },
  { id: "herbs", label: "Herb Library", icon: IconPlant },
  { id: "saved", label: "Saved Answers", icon: IconBookmark },
  { id: "about", label: "About This Tool", icon: IconInfo },
];

export function Sidebar({
  view,
  onNavigate,
  onClose,
  activeConversationId,
  conversationRefresh,
  onSelectConversation,
  onNewConversation,
}: SidebarProps) {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);

  const load = useCallback(() => {
    fetchConversations()
      .then(setConversations)
      .catch(() => {
        /* backend may not be running yet */
      });
  }, []);

  useEffect(() => {
    load();
  }, [load, conversationRefresh]);

  async function handleDelete(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    try {
      await deleteConversation(id);
    } catch {
      /* non-fatal */
    }
    load();
  }

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

      <div className="sidebar__threads">
        <div className="sidebar__threads-head">
          <span>Conversations</span>
          <button
            className="thread-new"
            title="New conversation"
            onClick={() => {
              onNewConversation();
              onClose();
            }}
          >
            <IconPlus width={15} height={15} />
          </button>
        </div>

        {conversations.length === 0 ? (
          <p className="sidebar__threads-empty">No conversations yet</p>
        ) : (
          <ul className="thread-list">
            {conversations.map((c) => (
              <li key={c.id} className="thread-row">
                <button
                  className={`thread-item ${
                    view === "chat" && activeConversationId === c.id
                      ? "thread-item--active"
                      : ""
                  }`}
                  onClick={() => {
                    onSelectConversation(c.id);
                    onClose();
                  }}
                >
                  <IconChat width={14} height={14} />
                  <span className="thread-item__title">{c.title}</span>
                  <span className="thread-item__count">{c.message_count}</span>
                </button>
                <button
                  className="thread-item__delete"
                  title="Delete conversation"
                  onClick={(e) => void handleDelete(e, c.id)}
                >
                  <IconTrash width={13} height={13} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="sidebar__footer">
        <div className="sidebar__chip">
          Not a diagnosis tool — always know when to see a doctor.
        </div>
      </div>
    </aside>
  );
}