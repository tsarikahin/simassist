
import { Terminal } from "lucide-react";

export function SolverConsole() {
  return (
    <div className="solver-console">
      <div className="panel-heading">
        <Terminal size={16} />
        Solver Console
        <span className="console-status">Idle</span>
      </div>

      <div className="console-output">
        <p>[system] SimAssist initialized.</p>
        <p>[system] Waiting for simulation...</p>
      </div>
    </div>
  );
}
