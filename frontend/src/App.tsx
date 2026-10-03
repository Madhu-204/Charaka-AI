import { useCallback, useEffect, useState } from "react";
import type { ViewName } from "./types";
import type { AuthUser } from "./api";
import { fetchAuthConfig, fetchMe, logout, setToken, setUnauthorizedHandler } from "./api";
import type { ReasoningContent } from "./components/ReasoningPanel";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Sidebar } from "./components/Sidebar";
import { ReasoningPanel } from "./components/ReasoningPanel";
import { AuthView } from "./views/AuthView";
import { ChatView } from "./views/ChatView";
import { HerbLibraryView } from "./views/HerbLibraryView";
import { SavedAnswersView } from "./views/SavedAnswersView";
import { AboutView } from "./views/AboutView";
import { IconAlert, IconMenu } from "./components/Icons";

type AuthPhase = "checking" | "ready" | "signedOut";

export default function App() {
  const [view, setView] = useState<ViewName>("chat");
  const [reasoning, setReasoning] = useState<ReasoningContent | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversationRefresh, setConversationRefresh] = useState(0);

  const [user, setUser] = useState<AuthUser | null>(null);
  const [authPhase, setAuthPhase] = useState<AuthPhase>("checking");
  const [needsRegistration, setNeedsRegistration] = useState(false);
  const [authRequired, setAuthRequired] = useState(true);

  // Validate the stored token once on load. A stale or revoked token must land
  // on the sign-in screen rather than failing on the first question.
  //
  // When the server says accounts are off (CHARAKA_AUTH_REQUIRED=0), go straight
  // to the dashboard: there is no session to validate, so the sign-in screen is
  // skipped entirely and AuthView is never rendered.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const config = await fetchAuthConfig();
        if (cancelled) return;
        setNeedsRegistration(config.needs_registration);
        setAuthRequired(config.auth_required);
        if (!config.auth_required) {
          setAuthPhase("ready");
          return;
        }
        const me = await fetchMe();
        if (cancelled) return;
        setUser(me);
        setAuthPhase(me ? "ready" : "signedOut");
      } catch {
        if (!cancelled) setAuthPhase("signedOut");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // A 401 normally means the session is gone: drop it and show sign-in. But a
  // 401 does not imply that when accounts are off -- /eval/* and /traces are
  // gated by their own admin key and answer 401 without it, and About renders
  // the eval panel. Bouncing to sign-in for that would resurrect the login
  // screen this build is meant to skip, so in that mode the token is dropped
  // and the calling panel surfaces its own error instead.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setToken(null);
      setUser(null);
      if (!authRequired) return;
      setConversationId(null);
      setReasoning(null);
      setAuthPhase("signedOut");
    });
  }, [authRequired]);

  const onAuthenticated = useCallback((next: AuthUser) => {
    setUser(next);
    setAuthPhase("ready");
    setConversationId(null);
    setReasoning(null);
  }, []);

  const onSignOut = useCallback(async () => {
    await logout();
    setToken(null);
    setUser(null);
    setConversationId(null);
    setReasoning(null);
    setAuthPhase("signedOut");
  }, []);

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

  const onDeleteConversation = useCallback(
    (id: string) => {
      if (id === conversationId) {
        setConversationId(null);
        setReasoning(null);
        setPanelOpen(false);
      }
    },
    [conversationId]
  );

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setMenuOpen(false);
        setPanelOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (authPhase === "checking") {
    return (
      <div className="auth auth--loading">
        <div className="auth__spinner" role="status" aria-label="Loading" />
      </div>
    );
  }

  if (authPhase === "signedOut") {
    return (
      <ErrorBoundary>
        <AuthView needsRegistration={needsRegistration} onAuthenticated={onAuthenticated} />
      </ErrorBoundary>
    );
  }

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
          onDeleteConversation={onDeleteConversation}
          user={user}
          onSignOut={onSignOut}
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
            {view === "saved" && <SavedAnswersView onReasoning={onReasoning} />}
            {view === "about" && <AboutView onReasoning={onReasoning} />}
          </ErrorBoundary>
        </main>

        <div
          className="app__backdrop"
          onClick={() => {
            setPanelOpen(false);
            setMenuOpen(false);
          }}
        />

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