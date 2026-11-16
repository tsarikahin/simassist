
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";

import {
  getProjectContext,
  getProjectGeometries,
  setActiveGeometry,
  type ProjectGeometry,
} from "../../services/projectContext";

import {
  Box,
  Bot,
  FolderTree,
  Pencil,
  Settings2,
  Trash2,
} from "lucide-react";

import { ProjectExplorer } from "../../features/projects/components/ProjectExplorer";
import { SimulationViewer } from "../../features/viewer/components/SimulationViewer";
import { AssistantPanel } from "../../features/assistant/components/AssistantPanel";
import { SolverConsole } from "../../features/solver/components/SolverConsole";

import { createProject, deleteProject, listProjects, openDefaultProject, openLegacyProject, renameProject, type WorkspaceProject } from "../../services/workspace";


const STORAGE_KEY = "simassist.workspace.layout.v1";

const DEFAULT_LAYOUT = {
  projectWidth: 250,
  assistantWidth: 340,
  consoleHeight: 230,
};

const MIN_PROJECT_WIDTH = 170;
const MIN_ASSISTANT_WIDTH = 260;
const MIN_CENTER_WIDTH = 320;
const MIN_VIEWER_HEIGHT = 220;
const MIN_CONSOLE_HEIGHT = 110;

const RESIZER_SIZE = 7;

type ResizeTarget = "project" | "assistant" | "console";

interface LayoutSizes {
  projectWidth: number;
  assistantWidth: number;
  consoleHeight: number;
}

function clamp(
  value: number,
  minimum: number,
  maximum: number,
): number {
  return Math.min(
    Math.max(value, minimum),
    Math.max(minimum, maximum),
  );
}

function readSavedLayout(): LayoutSizes {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);

    if (!stored) {
      return { ...DEFAULT_LAYOUT };
    }

    const parsed: unknown = JSON.parse(stored);

    if (!parsed || typeof parsed !== "object") {
      return { ...DEFAULT_LAYOUT };
    }

    const saved = parsed as Partial<LayoutSizes>;

    return {
      projectWidth:
        typeof saved.projectWidth === "number" &&
        Number.isFinite(saved.projectWidth)
          ? saved.projectWidth
          : DEFAULT_LAYOUT.projectWidth,

      assistantWidth:
        typeof saved.assistantWidth === "number" &&
        Number.isFinite(saved.assistantWidth)
          ? saved.assistantWidth
          : DEFAULT_LAYOUT.assistantWidth,

      consoleHeight:
        typeof saved.consoleHeight === "number" &&
        Number.isFinite(saved.consoleHeight)
          ? saved.consoleHeight
          : DEFAULT_LAYOUT.consoleHeight,
    };
  } catch {
    return { ...DEFAULT_LAYOUT };
  }
}

function saveLayout(layout: LayoutSizes) {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(layout),
    );
  } catch {
    // Workspace remains usable if storage is unavailable.
  }
}

function getAvailableWidth(
  workspaceWidth: number,
): number {
  return Math.max(
    0,
    workspaceWidth - RESIZER_SIZE * 2,
  );
}

// React StrictMode may replay mounting effects in development.
// Reuse the same startup request while the backend atomically reuses an empty default.
let bootPromise: Promise<[WorkspaceProject[], WorkspaceProject]> | null = null;

export function AppShell() {
  const [projectId, setProjectId] = useState("");
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [editingProjectName, setEditingProjectName] = useState<string | null>(null);
  const [savingProjectName, setSavingProjectName] = useState(false);
  const [deletingProject, setDeletingProject] = useState(false);
  const projectBusy = savingProjectName || deletingProject;

  useEffect(() => {
    // Empty auto-created chats do not require another untitled project on refresh.
    let mounted = true;
    if (!bootPromise) {
      bootPromise = openDefaultProject().then(async project => {
        return [await listProjects(), project] as [WorkspaceProject[], WorkspaceProject];
      }).catch(error => {
        bootPromise = null;
        throw error;
      });
    }
    void bootPromise.then(([available, selected]) => {
      if (!mounted) return;
      setProjects(available);
      setProjectId(selected.id);
    }).catch(error => {if (mounted) setWorkspaceError(String(error));});
    return () => {mounted = false;};
  }, []);

  const switchProject = (id: string) => {
    setEditingProjectName(null);
    setWorkspaceError(null);
    setProjectId(id);
    setActiveGeometryJobId(null);
    setPreviewArtifactId(null);
    setActiveJobIds([]);
    setProjectError(null);
    setProjectRevision(r => r + 1);
    setMeshCompletionRevision(0);
    setViewerSelectedMeshId(null);
    navigateViewer("geometry");
  };

  async function saveProjectName() {
    const name = editingProjectName?.trim();
    if (!name || savingProjectName) return;
    const id = projectId;
    setSavingProjectName(true);
    setWorkspaceError(null);
    try {
      await renameProject(id, name);
      setProjects(current => current.map(project => project.id === id ? {...project, name} : project));
      setEditingProjectName(null);
    } catch (error) {
      setWorkspaceError(String(error));
    } finally {
      setSavingProjectName(false);
    }
  }

  async function removeProject() {
    const selected = projects.find(project => project.id === projectId);
    if (!selected || projectBusy) return;
    if (!window.confirm(`Delete project "${selected.name}" and all its chat histories? This cannot be undone. Saved job records and simulation files will remain on disk.`)) return;
    setDeletingProject(true);
    setWorkspaceError(null);
    try {
      await deleteProject(selected.id);
      const remaining = projects.filter(project => project.id !== selected.id);
      setProjects(remaining);
      switchProject(remaining[0]?.id ?? "");
      if (!remaining.length) {
        const replacement = await openDefaultProject();
        setProjects([replacement]);
        switchProject(replacement.id);
      }
    } catch (error) {
      setWorkspaceError(String(error));
    } finally {
      setDeletingProject(false);
    }
  }

  const [previewArtifactId, setPreviewArtifactId] =
    useState<string | null>(null);

  const [activeJobIds, setActiveJobIds] =
    useState<string[]>([]);

  const [activeGeometryJobId, setActiveGeometryJobId] =
    useState<string | null>(null);

  const [projectRevision, setProjectRevision] = useState(0);
  const [viewerSelectedMeshId, setViewerSelectedMeshId] = useState<string | null>(null);
  const [meshCompletionRevision, setMeshCompletionRevision] = useState(0);
  const [viewerNavigation, setViewerNavigation] = useState<{
    mode: "geometry" | "mesh";
    meshJobId?: string;
    requestId: number;
  }>({mode: "geometry", requestId: 0});

  const navigateViewer = (mode: "geometry" | "mesh", meshJobId?: string) => {
    setViewerNavigation(previous => ({mode, meshJobId, requestId: previous.requestId + 1}));
  };
  const [projectError, setProjectError] =
    useState<string | null>(null);

  const [layout, setLayout] =
    useState<LayoutSizes>(readSavedLayout);

  const workspaceRef = useRef<HTMLElement>(null);
  const centerRef = useRef<HTMLElement>(null);

  const dragRef = useRef<{
    target: ResizeTarget;
    pointerId: number;
  } | null>(null);

  function updateLayout(
    updater: (previous: LayoutSizes) => LayoutSizes,
  ) {
    setLayout((previous) => {
      const next = updater(previous);
      saveLayout(next);
      return next;
    });
  }

  // Restore persisted active geometry without submitting jobs.
  useEffect(() => {
    const controller = new AbortController();

    async function restoreGeometry() {
      if (!projectId) return;
      try {
        const [context, geometries] = await Promise.all([
          getProjectContext(projectId, controller.signal),
          getProjectGeometries(projectId, controller.signal),
        ]);

        if (controller.signal.aborted) return;

        const selected = geometries.find(
          (geometry) => geometry.id === context.active_geometry_job_id,
        );

        if (!selected) {
          setActiveGeometryJobId(null);
          setPreviewArtifactId(null);
          return;
        }

        const previewId = selected.result?.preview_artifact_id;

        if (typeof previewId !== "string") {
          setProjectError("Active geometry has no preview artifact");
          return;
        }

        setActiveGeometryJobId(selected.id);
        setPreviewArtifactId(previewId);
        setProjectError(null);
      } catch (error) {
        if (controller.signal.aborted) return;
        setProjectError(
          error instanceof Error
            ? error.message
            : "Unable to restore project context",
        );
      }
    }

    void restoreGeometry();
    return () => controller.abort();
  }, [projectId]);

  // Select an existing completed geometry from Project Explorer.
  const handleSelectGeometry = useCallback(
    async (geometry: ProjectGeometry) => {
      const previewId = geometry.result?.preview_artifact_id;

      if (typeof previewId !== "string") {
        setProjectError("Selected geometry has no preview artifact");
        return;
      }

      try {
        await setActiveGeometry(projectId, geometry.id);
        setActiveGeometryJobId(geometry.id);
        setPreviewArtifactId(previewId);
        setProjectError(null);
      } catch (error) {
        setProjectError(
          error instanceof Error
            ? error.message
            : "Unable to select geometry",
        );
      }
    },
    [projectId],
  );

  // Persist newly completed geometry and show its preview.
  const handleGeometryCompleted = useCallback(
    (previewId: string, geometryJobId: string) => {
      setPreviewArtifactId(previewId);
      setProjectRevision((revision) => revision + 1);

      void setActiveGeometry(projectId, geometryJobId)
        .then(() => {
          setActiveGeometryJobId(geometryJobId);
          setProjectError(null);
        })
        .catch((error: unknown) => {
          setProjectError(
            error instanceof Error
              ? error.message
              : "Unable to save active geometry",
          );
        });
    },
    [projectId],
  );

  const handleMeshCompleted = useCallback((_meshJobId: string) => {
    setMeshCompletionRevision((revision) => revision + 1);
  }, []);

  function handleJobsSubmitted(submittedIds: string[]) {
    if (submittedIds.length === 0) return;

    setActiveJobIds((previous) => [
      ...new Set([...previous, ...submittedIds]),
    ]);
  }

  function resizePanel(
    target: ResizeTarget,
    clientX: number,
    clientY: number,
  ) {
    const workspace = workspaceRef.current;
    const center = centerRef.current;

    if (!workspace || !center) return;

    const workspaceRect =
      workspace.getBoundingClientRect();

    const centerRect =
      center.getBoundingClientRect();

    updateLayout((previous) => {
      const next = { ...previous };

      const availableWidth = getAvailableWidth(
        workspaceRect.width,
      );

      if (target === "project") {
        const maximum = availableWidth -
          previous.assistantWidth -
          MIN_CENTER_WIDTH;

        next.projectWidth = clamp(
          clientX - workspaceRect.left,
          MIN_PROJECT_WIDTH,
          maximum,
        );
      }

      if (target === "assistant") {
        const maximum = availableWidth -
          previous.projectWidth -
          MIN_CENTER_WIDTH;

        next.assistantWidth = clamp(
          workspaceRect.right - clientX,
          MIN_ASSISTANT_WIDTH,
          maximum,
        );
      }

      if (target === "console") {
        const maximum = centerRect.height -
          MIN_VIEWER_HEIGHT -
          RESIZER_SIZE;

        next.consoleHeight = clamp(
          centerRect.bottom - clientY,
          MIN_CONSOLE_HEIGHT,
          maximum,
        );
      }

      return next;
    });
  }

  function startResize(
    event: ReactPointerEvent<HTMLDivElement>,
    target: ResizeTarget,
  ) {
    if (event.button !== 0) return;

    event.preventDefault();

    dragRef.current = {
      target,
      pointerId: event.pointerId,
    };

    event.currentTarget.setPointerCapture(
      event.pointerId,
    );

    resizePanel(
      target,
      event.clientX,
      event.clientY,
    );
  }

  function moveResize(
    event: ReactPointerEvent<HTMLDivElement>,
  ) {
    const drag = dragRef.current;

    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }

    resizePanel(
      drag.target,
      event.clientX,
      event.clientY,
    );
  }

  function endResize(
    event: ReactPointerEvent<HTMLDivElement>,
  ) {
    if (
      dragRef.current?.pointerId !== event.pointerId
    ) {
      return;
    }

    dragRef.current = null;

    if (
      event.currentTarget.hasPointerCapture(
        event.pointerId,
      )
    ) {
      event.currentTarget.releasePointerCapture(
        event.pointerId,
      );
    }
  }

  function handleResizeKey(
    event: ReactKeyboardEvent<HTMLDivElement>,
    target: ResizeTarget,
  ) {
    const step = event.shiftKey ? 40 : 10;

    if (target === "console") {
      if (
        event.key !== "ArrowUp" &&
        event.key !== "ArrowDown"
      ) {
        return;
      }

      event.preventDefault();

      const center = centerRef.current;
      if (!center) return;

      const maximum =
        center.getBoundingClientRect().height -
        MIN_VIEWER_HEIGHT -
        RESIZER_SIZE;

      updateLayout((previous) => ({
        ...previous,
        consoleHeight: clamp(
          previous.consoleHeight +
            (event.key === "ArrowUp" ? step : -step),
          MIN_CONSOLE_HEIGHT,
          maximum,
        ),
      }));

      return;
    }

    if (
      event.key !== "ArrowLeft" &&
      event.key !== "ArrowRight"
    ) {
      return;
    }

    event.preventDefault();

    const workspace = workspaceRef.current;
    if (!workspace) return;

    const availableWidth = getAvailableWidth(
      workspace.getBoundingClientRect().width,
    );

    updateLayout((previous) => {
      if (target === "project") {
        return {
          ...previous,
          projectWidth: clamp(
            previous.projectWidth +
              (event.key === "ArrowRight" ? step : -step),
            MIN_PROJECT_WIDTH,
            availableWidth -
              previous.assistantWidth -
              MIN_CENTER_WIDTH,
          ),
        };
      }

      return {
        ...previous,
        assistantWidth: clamp(
          previous.assistantWidth +
            (event.key === "ArrowLeft" ? step : -step),
          MIN_ASSISTANT_WIDTH,
          availableWidth -
            previous.projectWidth -
            MIN_CENTER_WIDTH,
        ),
      };
    });
  }

  function makeResizerProps(
    target: ResizeTarget,
  ) {
    return {
      onPointerDown: (
        event: ReactPointerEvent<HTMLDivElement>,
      ) => startResize(event, target),
      onPointerMove: moveResize,
      onPointerUp: endResize,
      onPointerCancel: endResize,
      onLostPointerCapture: () => {
        dragRef.current = null;
      },
      onKeyDown: (
        event: ReactKeyboardEvent<HTMLDivElement>,
      ) => handleResizeKey(event, target),
    };
  }

  const workspaceStyle: CSSProperties = {
    gridTemplateColumns:
      `${layout.projectWidth}px ` +
      `${RESIZER_SIZE}px ` +
      `minmax(0, 1fr) ` +
      `${RESIZER_SIZE}px ` +
      `${layout.assistantWidth}px`,
  };

  const centerStyle: CSSProperties = {
    gridTemplateRows:
      `minmax(0, 1fr) ` +
      `${RESIZER_SIZE}px ` +
      `${layout.consoleHeight}px`,
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-brand">
          <Box size={22} />
          <strong>SimAssist</strong>
          <span className="app-version">
            v0.1.0
          </span>
        </div>

        <div className="app-header-actions">
          <span className="status-indicator">
            Local Workspace
          </span>

          <Settings2 size={19} />
        </div>
      </header>

      <main
        ref={workspaceRef}
        className="workspace workspace-resizable"
        style={workspaceStyle}
      >
        <aside className="project-panel">
          <div className="panel-heading">
            <FolderTree size={16} />
            Project Explorer
          </div>

          <div className="workspace-project-switcher">
            <select className="workspace-select" aria-label="Select project" disabled={projectBusy} value={projectId} onChange={event => switchProject(event.target.value)}>
              {projects.map(project => <option key={project.id} value={project.id}>{project.name} ({project.id.slice(0, 6)})</option>)}
            </select>
            <button type="button" title="Rename project" aria-label="Rename project" disabled={!projectId || projectBusy} onClick={() => {
              setWorkspaceError(null);
              setEditingProjectName(projects.find(project => project.id === projectId)?.name ?? "");
            }}><Pencil size={14} /></button>
            <button type="button" className="workspace-delete-project" title="Delete project" aria-label="Delete project" disabled={!projectId || projectBusy} onClick={() => void removeProject()}><Trash2 size={14} /></button>
            <button type="button" disabled={projectBusy} title="Create empty project" onClick={() => void createProject().then(project => {
              setProjects(current => [project, ...current]);
              switchProject(project.id);
            }).catch(error => setWorkspaceError(String(error)))}>+ Project</button>
            <button type="button" disabled={projectBusy} title="Open previously existing demo project" onClick={() => void openLegacyProject().then(project => {
              setProjects(current => [project, ...current.filter(item => item.id !== project.id)]);
              switchProject(project.id);
            }).catch(error => setWorkspaceError(String(error)))}>Legacy</button>
          </div>
          {editingProjectName !== null && <form className="workspace-project-name" onSubmit={event => {
            event.preventDefault();
            void saveProjectName();
          }}>
            <label htmlFor="project-name">Project name</label>
            <input id="project-name" autoFocus required maxLength={120} value={editingProjectName}
              disabled={projectBusy} onChange={event => setEditingProjectName(event.target.value)}
              onKeyDown={event => {
                if (event.key === "Escape" && !projectBusy) setEditingProjectName(null);
              }} />
            <div>
              <button type="submit" disabled={projectBusy || !editingProjectName.trim()}>{savingProjectName ? "Saving…" : "Save"}</button>
              <button type="button" disabled={projectBusy} onClick={() => setEditingProjectName(null)}>Cancel</button>
            </div>
          </form>}
          {workspaceError && <p role="alert" style={{fontSize:12,color:"#fb7185"}}>{workspaceError}</p>}
          {projectId && <ProjectExplorer
            projectId={projectId}
            activeGeometryJobId={activeGeometryJobId}
            revision={projectRevision}
            meshRevision={meshCompletionRevision}
            selectedMeshJobId={viewerSelectedMeshId}
            onSelectGeometry={(geometry) => {
              setViewerSelectedMeshId(null);
              navigateViewer("geometry");
              void handleSelectGeometry(geometry);
            }}
            onSelectMesh={(geometry, meshJobId) => {
              setViewerSelectedMeshId(meshJobId);
              navigateViewer("mesh", meshJobId);
              void handleSelectGeometry(geometry);
            }}
            selectionError={projectError}
            onGeometryChanged={(deletedJobId) => {
              setProjectRevision(r => r + 1);
              if (deletedJobId && deletedJobId === activeGeometryJobId) {
                setActiveGeometryJobId(null);
                setPreviewArtifactId(null);
              }
            }}
          />}
        </aside>

        <div
          className="workspace-resizer workspace-resizer-vertical"
          role="separator"
          tabIndex={0}
          aria-label="Resize Project Explorer"
          aria-orientation="vertical"
          {...makeResizerProps("project")}
        />

        <section
          ref={centerRef}
          className="workspace-center workspace-center-resizable"
          style={centerStyle}
        >
          <div className="viewer-panel">
            <div className="panel-heading">
              <Box size={16} />
              Simulation Viewer
            </div>

            {projectId && <SimulationViewer key={projectId}
              projectId={projectId}
              previewArtifactId={previewArtifactId}
              geometryJobId={activeGeometryJobId}
              refreshRevision={meshCompletionRevision}
              navigation={viewerNavigation}
              onSelectedMesh={setViewerSelectedMeshId}
            />}
          </div>

          <div
            className="workspace-resizer workspace-resizer-horizontal"
            role="separator"
            tabIndex={0}
            aria-label="Resize Workflow Monitor"
            aria-orientation="horizontal"
            {...makeResizerProps("console")}
          />

          <div className="console-panel">
            {projectId && <SolverConsole key={projectId}
              projectId={projectId}
              jobIds={activeJobIds}
              onPreviewReady={handleGeometryCompleted}
              onMeshCompleted={handleMeshCompleted}
            />}
          </div>
        </section>

        <div
          className="workspace-resizer workspace-resizer-vertical"
          role="separator"
          tabIndex={0}
          aria-label="Resize AI Assistant"
          aria-orientation="vertical"
          {...makeResizerProps("assistant")}
        />

        <aside className="assistant-panel">
          <div className="panel-heading">
            <Bot size={16} />
            AI Assistant
          </div>

          {projectId && <AssistantPanel key={projectId}
            projectId={projectId}
            onJobsSubmitted={handleJobsSubmitted}
          />}
        </aside>
      </main>
    </div>
  );
}
