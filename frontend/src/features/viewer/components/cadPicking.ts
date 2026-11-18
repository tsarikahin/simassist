import type { EntityDimension } from "../../../services/cadEntities";
import type { GeometryPreview } from "../../../services/previews";

export function selectionLimitation(preview: GeometryPreview, dimension: EntityDimension): string | null {
  if (!preview.entities?.some(entity => entity.dimension === dimension)) {
    return `This geometry has no ${["CAD vertices", "CAD edges", "CAD faces", "CAD bodies"][dimension]} available for selection.`;
  }
  const mappings = [preview.vertex_entity_keys, preview.edge_entity_keys, preview.triangle_face_keys, preview.triangle_face_keys];
  if (!mappings[dimension]?.length) return "The CAD preview has no picking provenance for this entity type.";
  return null;
}

export function resolveCadPick(preview: GeometryPreview, dimension: EntityDimension, key: string | null, cellIndex?: number) {
  if (key === null) return { entity: null, issue: null };
  let entity = preview.entities?.find(candidate => candidate.entity_key === key);
  if (dimension === 3 && entity?.dimension === 2) {
    if (entity.owner_body_keys.length !== 1) {
      return { entity: null, issue: entity.owner_body_keys.length ? "This face belongs to multiple CAD bodies. Pick an exterior face with one owning body." : "This CAD face has no owning volume. A body cannot be selected here." };
    }
    const bodyKey = entity.owner_body_keys[0];
    entity = preview.entities?.find(candidate => candidate.entity_key === bodyKey);
  }
  if (!entity || entity.dimension !== dimension || entity.geometry_revision_id !== preview.geometry_revision_id) {
    return { entity: null, issue: "The picked entity has no valid CAD provenance for this selection mode." };
  }
  if (dimension === 0 && entity.coordinates && preview.entities?.some(other => other.dimension === 0 && other.entity_key !== key && other.coordinates?.every((value, index) => value === entity!.coordinates![index]))) {
    return { entity: null, issue: "Multiple CAD vertices occupy this position. This pick cannot identify a unique vertex." };
  }
  if (dimension === 1 && cellIndex !== undefined && preview.edge_segments?.[cellIndex]) {
    const signature = (segment: [number, number]) => segment.map(index => preview.points[index].join(",")).sort().join("|");
    const picked = signature(preview.edge_segments[cellIndex]);
    if (preview.edge_segments.some((segment, index) => preview.edge_entity_keys?.[index] !== key && signature(segment) === picked)) {
      return { entity: null, issue: "Multiple CAD edges overlap here. This pick cannot identify a unique edge." };
    }
  }
  return { entity, issue: null };
}
