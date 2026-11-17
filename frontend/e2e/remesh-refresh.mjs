import { chromium, expect } from "@playwright/test";
import { preview } from "vite";
import assert from "node:assert/strict";

// Exercise the real chat -> job SSE -> AppShell -> viewer refresh chain.
const server = await preview({ preview: { host: "127.0.0.1", port: 4179, strictPort: true } });
const browser = await chromium.launch({
  channel: "msedge", headless: true,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
});
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const project = { id: "project-a", name: "Remesh regression", created_at: "2026-01-01" };
  const chat = { id: "chat-a", project_id: project.id, title: "Remesh", created_at: project.created_at };
  const geometry = {
    id: "geometry-a", project_id: project.id, type: "geometry.create", status: "completed",
    created_at: project.created_at, input: { name: "Box", definition: { primitive: "box" } },
    result: { artifact_id: "geometry-artifact", preview_artifact_id: "cad-preview" },
  };
  const mesh = (id, min, max) => ({
    job_id: id, artifact_id: `${id}-artifact`, created_at: project.created_at,
    settings: { dimension: 3, min_size: min, max_size: max, element_family: "tetrahedral" },
    metadata: { node_count: 4, element_count: 1 },
  });
  const original = mesh("original-mesh", 2, 5);
  const finer = mesh("finer-mesh", 0.5, 1);
  let completed = false;
  let versionReads = 0;
  let submissions = 0;
  let selected = original.job_id;
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  const surface = {
    points: [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
    triangles: [[0, 1, 2], [0, 3, 1], [1, 3, 2], [0, 2, 3]],
    point_count: 4, triangle_count: 4, dimension: 3,
  };
  const context = () => ({ project_id: project.id, active_geometry_job_id: geometry.id,
    active_geometry_artifact_id: "geometry-artifact", selected_mesh_job_id: selected });
  const event = (name, data) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const json = value => route.fulfill({ json: value });
    if (path.endsWith("/workspace/projects/default")) return json(project);
    if (path.endsWith("/workspace/projects")) return json([project]);
    if (path.endsWith("/messages")) return json([]);
    if (path.endsWith("/chats")) return json([chat]);
    if (path.endsWith("/chat/models")) return json({ models: ["test"], default_model: "test" });
    if (path.endsWith("/geometries")) return json([geometry]);
    if (path.endsWith("/context")) return json(context());
    if (path.endsWith("/selected-mesh")) {
      selected = route.request().postDataJSON().mesh_job_id;
      return json(context());
    }
    if (path.endsWith("/meshes")) {
      versionReads++;
      return json(completed ? [finer, original] : [original]);
    }
    if (path.includes("/cad-previews/")) return json(surface);
    if (path.endsWith("/preview")) return json({ ...surface, source_node_count: 4,
      volume_element_count: 1, mesh_job_id: selected, mesh_artifact_id: `${selected}-artifact` });
    if (path.endsWith("/chat/stream")) {
      submissions++;
      return route.fulfill({ contentType: "text/event-stream", body:
        event("jobs", { job_ids: [finer.job_id] }) +
        event("done", { message: `Submitted mesh job ${finer.job_id}`, submitted_job_ids: [finer.job_id] }) });
    }
    if (path.endsWith(`/jobs/${finer.job_id}/events`)) {
      completed = true;
      const job = { id: finer.job_id, project_id: project.id, type: "mesh.generate",
        status: "completed", input: { settings: finer.settings }, result: finer.metadata };
      return route.fulfill({ contentType: "text/event-stream", body: event("job", job) + event("end", job) });
    }
    throw new Error(`Unexpected API request ${path}`);
  });
  await page.goto("http://127.0.0.1:4179");
  await page.getByRole("button", { name: "Mesh", exact: true }).click();
  const versions = page.getByRole("combobox", { name: "Mesh version" });
  await expect(versions.locator("option")).toHaveCount(1);
  const before = versionReads;
  await page.getByPlaceholder("Describe your simulation...").fill("Remesh it using min 0.5 mm and max 1 mm");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(versions.locator("option")).toHaveCount(2);
  await expect(versions).toHaveValue(original.job_id);
  assert.ok(versionReads > before, "mesh completion reloads version list");
  await versions.selectOption(finer.job_id);
  await expect(page.getByLabel("Mesh statistics")).toContainText("finer-me");
  assert.equal(submissions, 1, "jobs and done events do not resubmit the request");
  assert.deepEqual(errors, []);
  console.log("Passed remesh SSE completion refresh and separate mesh version selection");
} finally {
  await browser.close();
  await new Promise(resolve => server.httpServer.close(resolve));
}
