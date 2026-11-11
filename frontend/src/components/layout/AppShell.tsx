
import { Box, Bot, FolderTree, Settings2 } from "lucide-react";

import { ProjectExplorer } from "../../features/projects/components/ProjectExplorer";
import { SimulationViewer } from "../../features/viewer/components/SimulationViewer";
import { AssistantPanel } from "../../features/assistant/components/AssistantPanel";
import { SolverConsole } from "../../features/solver/components/SolverConsole";

export function AppShell() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-brand">
          <Box size={22} />
          <strong>SimAssist</strong>
          <span className="app-version">v0.1.0</span>
        </div>

        <div className="app-header-actions">
          <span className="status-indicator">Local Workspace</span>
          <Settings2 size={19} />
        </div>
      </header>

      <main className="workspace">
        <aside className="project-panel">
          <div className="panel-heading">
            <FolderTree size={16} />
            Project Explorer
          </div>
          <ProjectExplorer />
        </aside>

        <section className="workspace-center">
          <div className="viewer-panel">
            <div className="panel-heading">
              <Box size={16} />
              Simulation Viewer
            </div>
            <SimulationViewer />
          </div>

          <div className="console-panel">
            <SolverConsole />
          </div>
        </section>

        <aside className="assistant-panel">
          <div className="panel-heading">
            <Bot size={16} />
            AI Assistant
          </div>
          <AssistantPanel />
        </aside>
      </main>
    </div>
  );
}
