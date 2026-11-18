import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";

const api = process.env.CAD_API_URL ?? "http://127.0.0.1:8003";
const browser = await chromium.launch({ channel: "msedge", headless: true,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"] });
try {
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
  const page = await context.newPage();
  const fixture = await (await context.request.get(`${api}/benchmark/config`)).json();
  const project = fixture.project.id;
  const base = `${api}/api/projects/${project}`;
  await context.request.put(`${base}/active-geometry`, { data: { geometry_job_id: fixture.geometries[0].job_id } });
  await context.request.put(`${base}/geometry-selection`, { data: { geometry_revision_id: fixture.geometries[0].artifact_id, dimension: null, tag: null } });
  const errors = [];
  page.on("pageerror", error => { errors.push(error.message); console.error(error.stack); });
  await page.addInitScript(() => {
    window.viewerEvents = [];
    window.addEventListener("simassist:viewer-performance", event => window.viewerEvents.push(event.detail));
  });
  let downloads = 0;
  page.on("request", request => { if (request.url().includes("/cad-previews/")) downloads++; });
  await page.goto(`${process.env.VIEWER_URL ?? "http://127.0.0.1:4176"}/?viewerDebug=1`);
  const inspector = page.getByRole("region", { name: "Geometry Inspector" });
  await expect(inspector).toContainText("No selection");
  await expect(page.getByRole("button", { name: "View +Z", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "View +Z", exact: true }).click();
  async function pickCenter(x = .5, y = .5) {
    await expect(page.getByRole("button", { name: "View +Z", exact: true })).toBeEnabled();
    const rect = await page.locator(".vtk-render-surface").boundingBox();
    const saved = page.waitForResponse(response => response.url().endsWith("/geometry-selection") && response.request().method() === "PUT");
    await page.mouse.click(rect.x + rect.width * x, rect.y + rect.height * y);
    assert.equal((await saved).status(), 200);
    await expect(inspector).toContainText(/Face \d+/);
    return (await (await context.request.get(`${base}/geometry-selection`)).json()).selection;
  }
  const top = await pickCenter();
  assert.equal(top.geometric_type, "Plane");
  assert.ok(Math.abs(top.area - 400) < 1e-6);
  assert.ok(Math.abs(top.bounds[2] - 20) < 1e-5);
  const previews = downloads;
  const highlight = await page.evaluate(() => window.viewerEvents.filter(e => e.kind === "cad-highlight" && e.face_key).at(-1));
  const preview = await (await context.request.get(`${base}/cad-previews/${fixture.geometries[0].preview_artifact_id}`)).json();
  assert.equal(highlight.triangle_count, preview.triangle_face_keys.filter(key => key === top.entity_key).length);
  assert.ok(highlight.triangle_count > 1, "whole face, not a triangle");
  await page.getByRole("button", { name: "View +X", exact: true }).click();
  await expect(inspector).toContainText(top.label);
  const side = await pickCenter();
  assert.notEqual(side.entity_key, top.entity_key);
  const orbitRect = await page.locator(".vtk-render-surface").boundingBox();
  const writes = [];
  const recordWrite = request => { if (request.url().endsWith("/geometry-selection") && request.method() === "PUT") writes.push(request.url()); };
  page.on("request", recordWrite);
  await page.mouse.move(orbitRect.x + orbitRect.width * .5, orbitRect.y + orbitRect.height * .5);
  await page.mouse.down();
  await page.mouse.move(orbitRect.x + orbitRect.width * .6, orbitRect.y + orbitRect.height * .6, { steps: 10 });
  await page.mouse.up();
  await expect(inspector).toContainText(side.label);
  assert.equal(writes.length, 0, "orbit must not select a face");
  page.off("request", recordWrite);
  // Hover must leave authoritative selection unchanged.
  const rect = await page.locator(".vtk-render-surface").boundingBox();
  await page.mouse.move(rect.x + rect.width * .52, rect.y + rect.height * .52);
  await expect.poll(() => page.evaluate(() => window.viewerEvents.filter(e => e.kind === "cad-highlight" && e.hovered).length)).toBeGreaterThan(0);
  assert.equal((await (await context.request.get(`${base}/geometry-selection`)).json()).selection.entity_key, side.entity_key);
  await page.getByRole("button", { name: "Mesh", exact: true }).click();
  await expect(inspector).toBeHidden();
  await page.getByRole("button", { name: "Geometry", exact: true }).click();
  await expect(inspector).toContainText(side.label);
  assert.equal(downloads, previews, "camera and mode changes reuse preview");
  await page.reload();
  await expect(inspector).toContainText(side.label);
  await page.getByRole("button", { name: "Clear selection" }).click();
  await expect(inspector).toContainText("No selection");
  await page.getByText("Planar plate", { exact: true }).click();
  await expect.poll(async () => (await (await context.request.get(`${base}/context`)).json()).active_geometry_artifact_id).toBe(fixture.geometries[1].artifact_id);
  await expect(inspector).toContainText("No selection");
  const plate = await pickCenter();
  assert.equal(plate.geometric_type, "Plane");
  assert.ok(Math.abs(plate.area - 400) < 1e-6);
  await page.locator(".vtk-render-surface").focus();
  await page.keyboard.press("Escape");
  await expect(inspector).toContainText("No selection");
  await page.getByText("Block with hole", { exact: true }).click();
  await expect.poll(async () => (await (await context.request.get(`${base}/context`)).json()).active_geometry_artifact_id).toBe(fixture.geometries[2].artifact_id);
  await expect(inspector).toContainText("No selection");
  await expect(page.getByRole("button", { name: "View +Z", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "View +Z", exact: true }).click();
  // Looking straight down the through hole must not select an invisible face.
  const holeRect = await page.locator(".vtk-render-surface").boundingBox();
  await page.mouse.click(holeRect.x + holeRect.width / 2, holeRect.y + holeRect.height / 2);
  await expect(inspector).toContainText("No selection");
  await page.getByRole("button", { name: "Reset camera", exact: true }).click();
  // Find a visible cylindrical wall using actual pointer picks in the hole region.
  let wall = null;
  for (const y of [.20, .23, .26, .29]) {
    for (const x of [.46, .49, .52, .55]) {
      const r = await page.locator(".vtk-render-surface").boundingBox();
      const saved = page.waitForResponse(response => response.url().endsWith("/geometry-selection") && response.request().method() === "PUT");
      await page.mouse.click(r.x + r.width * x, r.y + r.height * y);
      await saved;
      await expect(inspector).toHaveAttribute("aria-busy", "false");
      wall = (await (await context.request.get(`${base}/geometry-selection`)).json()).selection;
      if (wall?.geometric_type === "Cylinder") break;
    }
    if (wall?.geometric_type === "Cylinder") break;
  }
  assert.equal(wall?.geometric_type, "Cylinder");
  assert.equal(wall.normal, null);
  await expect(inspector).toContainText("Normal varies");
  const jobs = await (await context.request.get(`${base}/jobs`)).json();
  assert.ok(jobs.every(job => job.type === "geometry.create"), "no FEM mesh generated");
  assert.deepEqual(errors, []);
  await page.screenshot({ path: "../.benchmarks/cad-faces.png" });
  // An external geometry switch must visibly reject an old viewer click.
  await context.request.put(`${base}/active-geometry`, { data: { geometry_job_id: fixture.geometries[0].job_id } });
  const staleRect = await page.locator(".vtk-render-surface").boundingBox();
  const rejected = page.waitForResponse(response => response.url().endsWith("/geometry-selection") && response.request().method() === "PUT");
  await page.mouse.click(staleRect.x + staleRect.width / 2, staleRect.y + staleRect.height / 2);
  assert.equal((await rejected).status(), 409);
  await expect(inspector.getByRole("alert")).toContainText("stale");
  await expect(inspector).toContainText("No selection");
  console.log("CAD picking passed: box whole-face highlight, metadata, hover, camera/modes/reload, clear/Escape, 2D, hole wall, no FEM mesh.");
} finally { await browser.close(); }
