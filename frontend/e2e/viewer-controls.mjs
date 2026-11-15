import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
const browser = await chromium.launch({
  channel: "msedge",
  headless: true,
  args: [
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--enable-webgl",
    "--ignore-gpu-blocklist",
  ],
});
const context = await browser.newContext({
  viewport: { width: 1600, height: 1000 },
});
const page = await context.newPage();
const fixture = await (
  await context.request.get("http://127.0.0.1:8002/benchmark/config")
).json();
await context.request.put(
  `http://127.0.0.1:8002/api/projects/${fixture.project.id}/active-geometry`,
  { data: { geometry_job_id: fixture.geometry_job_id } },
);
await context.request.put(
  `http://127.0.0.1:8002/api/projects/${fixture.project.id}/selected-mesh`,
  {
    data: {
      geometry_job_id: fixture.geometry_job_id,
      mesh_job_id: fixture.mesh_job_ids.at(-1),
    },
  },
);
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await page.addInitScript(() => {
  window.viewerEvents = [];
  window.addEventListener("simassist:viewer-performance", (event) =>
    window.viewerEvents.push(event.detail),
  );
});
let previewRequests = 0;
page.on("request", (request) => {
  if (request.url().endsWith("/preview") || request.url().endsWith("/download"))
    previewRequests++;
});
const url = process.env.VIEWER_URL || "http://127.0.0.1:4175";
await page.goto(`${url}/?viewerDebug=1`);
await page.getByText("Points:", { exact: false }).first().waitFor();
await page.getByRole("button", { name: "Mesh", exact: true }).click();
await page.getByText("Surface points:", { exact: false }).waitFor();
const version = page.getByRole("combobox", { name: "Mesh version" });
const old = fixture.mesh_job_ids[0];
await version.selectOption(old);
await expect
  .poll(async () => {
    const state = await (
      await context.request.get(
        `http://127.0.0.1:8002/api/projects/${fixture.project.id}/context`,
      )
    ).json();
    return state.selected_mesh_job_id;
  })
  .toBe(old);
await expect(page.getByLabel("Mesh statistics")).toContainText(old.slice(0, 8));
await page.getByText("Surface points:", { exact: false }).waitFor();
await expect(
  page.getByRole("button", { name: "Fit to view", exact: true }),
).toBeEnabled();
const before = previewRequests;
const scenesBefore = await page.evaluate(
  () => window.viewerEvents.filter((event) => event.kind === "scene").length,
);
for (const name of ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]) {
  await page.getByRole("button", { name: `View ${name}`, exact: true }).click();
  const event = await page.evaluate(() =>
    window.viewerEvents.filter((event) => event.kind === "camera").at(-1),
  );
  const axis = { X: 0, Y: 1, Z: 2 }[name[1]];
  event.direction.forEach((value, index) =>
    assert.ok(
      Math.abs(value - (index === axis ? (name[0] === "+" ? -1 : 1) : 0)) <
        1e-6,
    ),
  );
  event.direction.forEach((value, index) =>
    assert.ok(Math.abs(value - event.triad_direction[index]) < 1e-6),
  );
}
await page
  .getByRole("button", { name: "Orthographic projection", exact: true })
  .click();
await expect(
  page.getByRole("button", { name: "Orthographic projection", exact: true }),
).toHaveAttribute("aria-pressed", "true");
await page.getByLabel("Edges", { exact: true }).check();
await page.getByRole("button", { name: "Fit to view", exact: true }).click();
await page.getByRole("button", { name: "Reset camera", exact: true }).click();
await page.setViewportSize({ width: 1250, height: 850 });
await page.getByRole("button", { name: "View +Z", exact: true }).click();
await page.getByRole("button", { name: "Fit to view", exact: true }).click();
assert.equal(
  previewRequests,
  before,
  "camera/resize/edge controls must not download geometry",
);
assert.equal(
  await page.evaluate(
    () => window.viewerEvents.filter((event) => event.kind === "scene").length,
  ),
  scenesBefore,
  "controls must not rebuild vtk geometry",
);
await page.getByRole("button", { name: "Reset camera", exact: true }).click();
const directionBefore = await page.evaluate(
  () =>
    window.viewerEvents.filter((event) => event.kind === "camera").at(-1)
      .direction,
);
const surface = await page.locator(".vtk-render-surface").boundingBox();
await page.mouse.move(
  surface.x + surface.width * 0.55,
  surface.y + surface.height * 0.45,
);
await page.mouse.down();
for (let i = 1; i <= 30; i++) {
  await page.mouse.move(
    surface.x + surface.width * 0.55 + i * 3,
    surface.y + surface.height * 0.45 + i,
  );
  await page.waitForTimeout(20);
}
await page.mouse.up();
await expect
  .poll(async () =>
    page.evaluate(
      () =>
        window.viewerEvents.filter((event) => event.kind === "interaction")
          .length,
    ),
  )
  .toBeGreaterThan(0);
const events = await page.evaluate(() => window.viewerEvents);
const camera = events.filter((event) => event.kind === "camera").at(-1);
assert.ok(
  camera.direction.some(
    (value, index) => Math.abs(value - directionBefore[index]) > 0.01,
  ),
);
camera.direction.forEach((value, index) =>
  assert.ok(Math.abs(value - camera.triad_direction[index]) < 1e-6),
);
assert.equal(previewRequests, before);
const qualityRequests = [];
page.on("request", (request) => {
  if (request.url().endsWith("/quality")) qualityRequests.push(request.url());
});
const sceneCountBeforeQuality = await page.evaluate(
  () => window.viewerEvents.filter((event) => event.kind === "scene").length,
);
await page
  .getByRole("button", { name: "Inspect quality", exact: true })
  .click();
await expect(page.getByLabel("Mesh quality")).toContainText("Analyzed:", {
  timeout: 60000,
});
await page.getByRole("button", { name: "Hide details", exact: true }).click();
await page
  .getByRole("button", { name: "Inspect quality", exact: true })
  .click();
assert.equal(
  qualityRequests.length,
  1,
  "reopening quality uses the existing report",
);
assert.equal(previewRequests, before, "quality must not reload previews");
assert.equal(
  await page.evaluate(
    () => window.viewerEvents.filter((event) => event.kind === "scene").length,
  ),
  sceneCountBeforeQuality,
);
await page.getByRole("button", { name: "Hide details", exact: true }).click();
await page.getByRole("button", { name: "Fullscreen", exact: true }).click();
await expect
  .poll(() => page.evaluate(() => Boolean(document.fullscreenElement)))
  .toBe(true);
await page.getByRole("button", { name: "Fit to view", exact: true }).click();
await page.evaluate(() => document.exitFullscreen());
await page.getByRole("button", { name: "Geometry", exact: true }).click();
await page.getByText("Points:", { exact: false }).first().waitFor();
await page.getByRole("button", { name: "Mesh", exact: true }).click();
await page.getByText("Surface points:", { exact: false }).waitFor();
await expect(version).toHaveValue(old);
await page.reload();
await page.getByText("Points:", { exact: false }).first().waitFor();
await page.getByRole("button", { name: "Mesh", exact: true }).click();
await page.getByText("Surface points:", { exact: false }).waitFor();
await expect(version).toHaveValue(old);
for (const geometry of fixture.additional_geometries) {
  await page.getByText(geometry.name, { exact: true }).click();
  await page.getByText("Points:", { exact: false }).first().waitFor();
  await expect(
    page.getByRole("button", { name: "Orthographic projection", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "View +Z", exact: true }).click();
  await page.getByRole("button", { name: "Mesh", exact: true }).click();
  await page.getByText("Surface points:", { exact: false }).waitFor();
  await expect(page.getByLabel("Mesh statistics")).toContainText(
    `${geometry.dimension}D`,
  );
  await page.getByRole("button", { name: "View -X", exact: true }).click();
  await page.getByRole("button", { name: "Reset camera", exact: true }).click();
  const marker = await page.evaluate(() =>
    window.viewerEvents.filter((event) => event.kind === "camera").at(-1),
  );
  marker.direction.forEach((value, index) =>
    assert.ok(Math.abs(value - marker.triad_direction[index]) < 1e-6),
  );
}
await page.getByRole("button", { name: "+ Project", exact: true }).click();
await page
  .getByRole("heading", { name: "No geometry loaded", exact: true })
  .waitFor();
await page
  .getByRole("combobox", { name: "Select project", exact: true })
  .selectOption(fixture.project.id);
await page.getByText("Points:", { exact: false }).first().waitFor();
assert.deepEqual(errors, []);
const report = {
  passed: [
    "six standard camera directions",
    "XYZ triad follows camera",
    "fit/reset/projection/edges/resize preserve geometry allocation",
    "real mouse orbit",
    "version selection persists through modes and reload",
    "1D/2D geometry and mesh camera controls",
    "quality panel and fullscreen preserve selection and actor allocation",
    "project switch disposes and recreates VTK without losing persisted context",
  ],
  preview_requests: previewRequests,
  interaction: events.filter((event) => event.kind === "interaction"),
  errors,
};
await fs.writeFile(
  new URL(
    "../../.benchmarks/viewer-1118a/browser-controls.json",
    import.meta.url,
  ),
  JSON.stringify(report, null, 2),
);
console.log(JSON.stringify(report, null, 2));
await browser.close();
