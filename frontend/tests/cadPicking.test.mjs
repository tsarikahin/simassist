import assert from "node:assert/strict";
import { test } from "node:test";
import { resolveCadPick, selectionLimitation } from "../src/features/viewer/components/cadPicking.ts";

const revision = "revision-a";
const entity = (dimension, tag, extra = {}) => ({
  geometry_revision_id: revision, dimension, tag,
  entity_key: `${revision}:${dimension}:${tag}`, owner_body_keys: [], ...extra,
});
const vertex = entity(0, 1, {coordinates: [0, 0, 0]});
const edge = entity(1, 1);
const body = entity(3, 7);
const face = entity(2, 1, {owner_body_keys: [body.entity_key]});
const preview = {
  geometry_revision_id: revision, entities: [vertex, edge, face, body],
  points: [[0, 0, 0], [1, 0, 0]],
  vertex_entity_keys: [vertex.entity_key], vertex_point_indices: [0],
  edge_entity_keys: [edge.entity_key], edge_segments: [[0, 1]],
  triangle_face_keys: [face.entity_key],
};

test("vertex, edge and face picks resolve only their CAD dimensions", () => {
  for (const item of [vertex, edge, face]) {
    assert.equal(selectionLimitation(preview, item.dimension), null);
    assert.equal(resolveCadPick(preview, item.dimension, item.entity_key).entity, item);
    assert.ok(resolveCadPick(preview, (item.dimension + 1) % 3, item.entity_key).issue);
  }
});

test("body selection uses the owning volume, with its own CAD tag", () => {
  const result = resolveCadPick(preview, 3, face.entity_key);
  assert.equal(result.entity, body);
  assert.equal(result.entity.tag, 7);
  assert.equal(result.issue, null);
});

test("shared faces and standalone surfaces cannot silently select a body", () => {
  for (const owners of [[], [body.entity_key, "second-volume"]]) {
    const ambiguous = {...preview, entities: [body, {...face, owner_body_keys: owners}]};
    assert.equal(resolveCadPick(ambiguous, 3, face.entity_key).entity, null);
    assert.ok(resolveCadPick(ambiguous, 3, face.entity_key).issue);
  }
});

test("missing metadata and stale geometry cannot be used for selection", () => {
  assert.ok(selectionLimitation({...preview, entities: []}, 0));
  assert.ok(selectionLimitation({...preview, vertex_entity_keys: []}, 0));
  assert.ok(resolveCadPick(preview, 2, "mesh-cell-17").issue);
  assert.ok(resolveCadPick({...preview, geometry_revision_id: "new-revision"}, 2, face.entity_key).issue);
  assert.deepEqual(resolveCadPick(preview, 2, null), {entity: null, issue: null});
});

test("coincident vertices and overlapping CAD edges report ambiguity", () => {
  const coincident = {...preview, entities: [...preview.entities, entity(0, 2, {coordinates: [0, 0, 0]})]};
  assert.ok(resolveCadPick(coincident, 0, vertex.entity_key).issue);
  const overlapping = {...preview, edge_segments: [[0, 1], [1, 0]], edge_entity_keys: [edge.entity_key, "other-edge"]};
  assert.ok(resolveCadPick(overlapping, 1, edge.entity_key, 0).issue);
});
