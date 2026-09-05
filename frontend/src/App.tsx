import { useCallback, useState } from "react";
import type { ViewName } from "./types";
import type { ReasoningContent } from "./components/ReasoningPanel";
import { Sidebar } from "./components/Sidebar";
import { ReasoningPanel } from "./components/ReasoningPanel";
import { ChatView } from "./views/ChatView";
import { HerbLibraryView } from "./views/HerbLibraryView";
import { SavedAnswersView } from "./views/SavedAnswersView";
import { AboutView } from "./views/AboutView";
import { IconAlert, IconMenu } from "./components/Icons";

export default function App() {
  const [view, setView] = useState<ViewName>("chat");
  const [reasoning, setReasoning] = useState<ReasoningContent | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const onNavigate = useCallback((v: ViewName) => {
    setView(v);
    setPanelOpen(false);
  }, []);

  const onReasoning = useCallback((content: ReasoningContent | null) => {
    setReasoning(content);
  }, []);

  return (
    <div
      className={`app ${panelOpen ? "panel-open" : ""} ${menuOpen ? "menu-open" : ""}`}
    >
      <Sidebar view={view} onNavigate={onNavigate} onClose={() => setMenuOpen(false)} />

      <main className={`main-col ${view === "chat" ? "main-col--chat" : ""}`}>
        <div className="disclaimer-banner">
          <button
            className="menu-toggle"
            onClick={() => setMenuOpen((o) => !o)}
            aria-label="Toggle navigation"
          >
            <IconMenu width={16} height={16} />
            Menu
          </button>
          <span>General wellness guidance from classical texts — not a diagnosis.</span>
        </div>

        {view === "chat" && <ChatView onReasoning={onReasoning} />}
        {view === "herbs" && <HerbLibraryView onReasoning={onReasoning} />}
        {view === "saved" && <SavedAnswersView onReasoning={onReasoning} />}
        {view === "about" && <AboutView onReasoning={onReasoning} />}
      </main>

      <div className="app__backdrop" onClick={() => setPanelOpen(false)} />

      <button className="panel-toggle" onClick={() => setPanelOpen((o) => !o)}>
        <IconAlert width={15} height={15} />
        Sources &amp; Reasoning
      </button>

      <ReasoningPanel content={reasoning} onClose={() => setPanelOpen(false)} />
    </div>
  );
}