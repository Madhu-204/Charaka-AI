import { useCallback, useState } from "react";
import type { ViewName } from "./types";
import type { ReasoningContent } from "./components/ReasoningPanel";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Sidebar } from "./components/Sidebar";
import { ReasoningPanel } from "./components/ReasoningPanel";
import { ChatView } from "./views/ChatView";
import { CorpusView } from "./views/CorpusView";
import { HerbLibraryView } from "./views/HerbLibraryView";
import { SavedAnswersView } from "./views/SavedAnswersView";
import { AboutView } from "./views/AboutView";
import { IconAlert, IconMenu } from "./components/Icons";

export default function App() {
  const [view, setView] = useState<ViewName>("chat");
  const [reasoning, setReasoning] = useState<ReasoningContent | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversationRefresh, setConversationRefresh] = useState(0);

  const onNavigate = useCallback((v: ViewName) => {
    setView(v);
    setPanelOpen(false);
  }, []);

  const onReasoning = useCallback((content: ReasoningContent | null) => {
    setReasoning(content);
  }, []);

  const onConversationChange = useCallback((id: string | null) => {
    setConversationId(id);
    setConversationRefresh((n) => n + 1);
  }, []);

  const onSelectConversation = useCallback((id: string) => {
    setConversationId(id);
    setView("chat");
    setPanelOpen(false);
  }, []);

  const onNewConversation = useCallback(() => {
    setConversationId(null);
    setView("chat");
    setReasoning(null);
    setPanelOpen(false);
  }, []);

  return (
    <ErrorBoundary>
      <div
        className={`app ${panelOpen ? "panel-open" : ""} ${menuOpen ? "menu-open" : ""} ${
          view === "chat" ? "" : "app--no-panel"
        }`}
      >
        <Sidebar
          view={view}
          onNavigate={onNavigate}
          onClose={() => setMenuOpen(false)}
          activeConversationId={conversationId}
          conversationRefresh={conversationRefresh}
          onSelectConversation={onSelectConversation}
          onNewConversation={onNewConversation}
        />

        <main className={`main-col ${view === "chat" ? "main-col--chat" : ""}`}>
          <div
            className={`disclaimer-banner ${view === "chat" ? "" : "disclaimer-banner--plain"}`}
          >
            <button
              className="menu-toggle"
              onClick={() => setMenuOpen((o) => !o)}
              aria-label="Toggle navigation"
            >
              <IconMenu width={16} height={16} />
              Menu
            </button>
            {view === "chat" && (
              <span>General wellness guidance from classical texts — not a diagnosis.</span>
            )}
          </div>

          <ErrorBoundary>
            {view === "chat" && (
              <ChatView
                onReasoning={onReasoning}
                conversationId={conversationId}
                onConversationChange={onConversationChange}
              />
            )}
            {view === "herbs" && <HerbLibraryView onReasoning={onReasoning} />}
            {view === "explore" && <CorpusView />}
            {view === "saved" && <SavedAnswersView onReasoning={onReasoning} />}
            {view === "about" && <AboutView onReasoning={onReasoning} />}
          </ErrorBoundary>
        </main>

        <div className="app__backdrop" onClick={() => setPanelOpen(false)} />

        {view === "chat" && (
          <button className="panel-toggle" onClick={() => setPanelOpen((o) => !o)}>
            <IconAlert width={15} height={15} />
            Sources &amp; Reasoning
          </button>
        )}

        {view === "chat" && (
          <ErrorBoundary>
            <ReasoningPanel content={reasoning} onClose={() => setPanelOpen(false)} />
          </ErrorBoundary>
        )}
      </div>
    </ErrorBoundary>
  );
}