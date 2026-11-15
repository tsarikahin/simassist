import { chromium } from "@playwright/test";
import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";
const baseline = process.argv.includes("--baseline");
const output = new URL(
  `../../.benchmarks/viewer-1118a/browser-${baseline ? "before" : "after"}.json`,
  import.meta.url,
);
const browser = await chromium.launch({
  channel: "msedge",
  headless: true,
  args: [
    "--enable-webgl",
    "--ignore-gpu-blocklist",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
  ],
});
const context = await browser.newContext({
  viewport: { width: 1600, height: 1000 },
});
const api = "http://127.0.0.1:8002";
const fixture = await (
  await context.request.get(`${api}/benchmark/config`)
).json();
await context.request.put(
  `${api}/api/projects/${fixture.project.id}/active-geometry`,
  { data: { geometry_job_id: fixture.geometry_job_id } },
);
await context.request.put(
  `${api}/api/projects/${fixture.project.id}/selected-mesh`,
  {
    data: {
      geometry_job_id: fixture.geometry_job_id,
      mesh_job_id: fixture.mesh_job_ids.at(-1),
    },
  },
);
await context.request.post(`${api}/benchmark/reset-preview-cache`);
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.addInitScript(() => {
  window.viewerEvents = [];
  window.previewStages = [];
  window.rawDraws = { buffer_ms: 0, draw_ms: 0, draws: 0 };
  const originalJson = Response.prototype.json;
  Response.prototype.json = async function () {
    const started = performance.now();
    const text = await this.text();
    const transferred = performance.now();
    const value = JSON.parse(text);
    const parsed = performance.now();
    if (value?.points && value?.triangles)
      window.previewStages.push({
        url: this.url,
        text_ms: transferred - started,
        parse_ms: parsed - transferred,
        bytes: text.length,
        parsed_at: parsed,
      });
    return value;
  };
  for (const klass of [WebGLRenderingContext, WebGL2RenderingContext]) {
    for (const method of ["bufferData", "drawElements", "drawArrays"]) {
      const original = klass.prototype[method];
      klass.prototype[method] = function (...args) {
        const started = performance.now();
        const value = original.apply(this, args);
        const elapsed = performance.now() - started;
        if (method === "bufferData") window.rawDraws.buffer_ms += elapsed;
        else {
          window.rawDraws.draw_ms += elapsed;
          window.rawDraws.draws++;
          window.rawDraws.last_draw_at = performance.now();
        }
        return value;
      };
    }
  }
  window.addEventListener("simassist:viewer-performance", (e) =>
    window.viewerEvents.push(e.detail),
  );
});
await page.goto(
  `${process.env.VIEWER_URL || "http://127.0.0.1:5173"}/?viewerDebug=1`,
);
await page
  .getByText("Points:", { exact: false })
  .first()
  .waitFor({ timeout: 30000 });
const measurements = [];
for (const name of ["cold", "warm"]) {
  const started = performance.now();
  const responsePromise = page
    .waitForResponse(
      (r) => r.url().endsWith("/preview") && r.request().method() === "GET",
      { timeout: 60000 },
    )
    .catch(() => null);
  await page.getByRole("button", { name: "Mesh", exact: true }).click();
  let response;
  if (baseline || name === "cold") response = await responsePromise;
  await page
    .getByText("Surface points:", { exact: false })
    .waitFor({ timeout: 120000 });
  measurements.push({
    name,
    elapsed_ms: performance.now() - started,
    response_bytes: response ? (await response.body()).length : 0,
    server_timing: response?.headers()["server-timing"],
    cache: response?.headers()["x-preview-cache"],
  });
  await page.getByRole("button", { name: "Geometry", exact: true }).click();
  await page.getByText("Points:", { exact: false }).first().waitFor();
}
await page.getByRole("button", { name: "Mesh", exact: true }).click();
await page.getByText("Surface points:", { exact: false }).waitFor();
const coldEvents = await page.evaluate(() => window.viewerEvents);
const coldStages = await page.evaluate(() => window.previewStages);
await page.reload();
await page.getByText("Points:", { exact: false }).first().waitFor();
const warmStarted = performance.now();
const warmResponse = page.waitForResponse((r) => r.url().endsWith("/preview"), {
  timeout: 60000,
});
await page.getByRole("button", { name: "Mesh", exact: true }).click();
const warmed = await warmResponse;
await page
  .getByText("Surface points:", { exact: false })
  .waitFor({ timeout: 60000 });
measurements.push({
  name: "warm_backend_new_page",
  elapsed_ms: performance.now() - warmStarted,
  response_bytes: (await warmed.body()).length,
  server_timing: warmed.headers()["server-timing"],
  cache: warmed.headers()["x-preview-cache"],
});
const gl = await page
  .locator(".vtk-render-surface canvas")
  .first()
  .evaluate((canvas) => {
    const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    return {
      renderer: ext
        ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)
        : gl.getParameter(gl.RENDERER),
      vendor: gl.getParameter(gl.VENDOR),
    };
  });
const result = {
  browser: browser.version(),
  renderer: gl,
  measurements,
  errors,
  events: coldEvents.concat(await page.evaluate(() => window.viewerEvents)),
  stages: coldStages.concat(await page.evaluate(() => window.previewStages)),
  draw_calls_cpu: await page.evaluate(() => window.rawDraws),
};
await fs.writeFile(output, JSON.stringify(result, null, 2));
await page.screenshot({
  path: fileURLToPath(
    new URL(
      `../../.benchmarks/viewer-1118a/${baseline ? "before" : "after"}.png`,
      import.meta.url,
    ),
  ),
  fullPage: true,
});
console.log(JSON.stringify(result, null, 2));
await browser.close();
