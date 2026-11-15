"""Deterministic multi-label routing. Never submits actions or calls a classifier."""

import re
from dataclasses import dataclass

from .context import RoutingContext

ALIASES = {
    "geometry": r"\b(geometry|geometries|cad|annulus|disk|box|sphere|cylinder|rectangle|square|primitive|boolean|cut|fuse|intersect|import|circle|ring|cube|ball|line)\b",
    "meshing": r"\b(mesh|meshes|meshing|remesh|refine|finer|coarser|quad|quads|quadrilateral|triangular|tetrahedral|hex|hexahedral|nodes|elements)\b",
    "cad_inspection": r"\b(step|stp|upload|uploaded|attachment|attached|file|files|inspect|inspection|topology|bounds|dimensions|faces|edges)\b",
    "selections": r"\b(select|selection|selections|pick|highlight|name)\b.{0,55}\b(face|faces|surface|surfaces|region|regions|holes|bolt_holes)\b|\b(use|that|this)\s+(that\s+|this\s+)?face\b|\bnamed (selection|region)s?\b",
}
UNSUPPORTED = r"\b(solver|solve|simulation|simulate|material|materials|boundary condition|boundary conditions|loads|stress|displacement)\b"
FOLLOWUP = r"\b(yes|no|keep|same|confirm|cancel|reject|approve|sizes)\b"


@dataclass(frozen=True)
class RoutingDecision:
    domains: tuple[str, ...]
    reasons: tuple[str, ...]
    fallback: bool = False
    clarification_required: bool = False


def signals(message: str) -> set[str]:
    return {
        domain
        for domain, pattern in ALIASES.items()
        if re.search(pattern, message, re.IGNORECASE)
    }


def route(message: str, context: RoutingContext) -> RoutingDecision:
    text = message.lower()
    # Negative requests may discuss tools, but need no mutating capability. A
    # remaining independent clause is still routed ("don't mesh; create a disk").
    text = re.sub(
        r"\b(do not|don't|never)\s+(create|mesh|import|submit|generate)\b[^.;!?]*(?:[.;!?]|$)",
        " ",
        text,
    )
    text = re.sub(r"\bwithout\s+(meshing|a mesh|mesh generation)\b", " ", text)
    domains = signals(text)
    if (
        re.search(r"\b(jobs?)\b", text)
        and re.search(r"\b(status|completed|running|queued|failed)\b", text)
        and not re.search(r"\b(create|generate|import|remesh|mesh it)\b", text)
    ):
        domains.clear()
    reasons = [f"explicit_{name}" for name in sorted(domains)]
    unsupported = bool(re.search(UNSUPPORTED, text))
    if unsupported and not re.search(
        r"\b(geometry|cad|annulus|disk|box|sphere|cylinder|rectangle|square|boolean|primitive|import)\b",
        text,
    ):
        domains.discard("geometry")
    # CAD inspection is not geometry creation. CAD alone means inspection unless
    # import/create/edit or an explicit primitive also appears.
    if "cad_inspection" in domains and not re.search(
        r"\b(create|draw|build|import|edit|cut|fuse|intersect|annulus|disk|box|sphere|cylinder|rectangle|square)\b",
        text,
    ):
        domains.discard("geometry")
    if "meshing" in domains and not re.search(
        r"\b(create|draw|build|import|cut|fuse|intersect|annulus|disk|box|sphere|cylinder|rectangle|square|primitive|circle|ring|cube|ball|line)\b",
        text,
    ):
        domains.discard("geometry")
    if "selections" in domains:
        domains.add("cad_inspection")
    if context.attachment_formats:
        domains.add("cad_inspection")
        reasons.append("attachment_metadata")
    if (
        not context.geometry_job_id
        and context.recent_attachment_formats
        and re.search(r"\b(it|this|that|same)\b", text)
        and domains.intersection(
            {"meshing", "geometry", "cad_inspection", "selections"}
        )
    ):
        domains.add("cad_inspection")
        reasons.append("chat_attachment_reference")
        if "meshing" in domains:
            domains.add("geometry")
    if (
        "meshing" in domains
        and "cad_inspection" in domains
        and re.search(
            r"\b(import|step|stp|upload|uploaded|attached|attachment|file)\b", text
        )
    ):
        domains.add("geometry")
        reasons.append("uploaded_mesh_workflow")
    if context.attachment_formats and "meshing" in domains:
        domains.add("geometry")
    if context.pending_remesh and re.search(FOLLOWUP, text):
        domains.add("meshing")
        reasons.append("chat_pending_remesh")
    if "meshing" in domains and (
        context.selected_mesh_job_id or context.has_completed_mesh
    ):
        reasons.append("active_mesh_context")
    if unsupported:
        reasons.append("unsupported_simulation")
    fallback = clarification = False
    if not domains:
        if re.search(r"\b(yes|no|confirm|approve|keep|cancel)\b", text):
            reasons.append("no_pending_confirmation")
            clarification = True
        elif re.search(r"\b(it|this|that|same|again)\b", text) and not unsupported:
            previous = signals(context.recent_intent)
            # Context can expose tools, but never authorizes repeating an action.
            if context.has_completed_mesh or context.selected_mesh_job_id:
                domains.add("meshing")
                reasons.append("active_mesh_followup")
            elif previous:
                domains.update(previous)
                reasons.append("recent_user_intent")
            elif context.geometry_job_id:
                domains.update(("geometry", "meshing"))
                reasons.append("active_geometry_ambiguous")
            else:
                reasons.append("missing_context")
            fallback = clarification = True
        elif re.search(r"\b(change|modify|make|do|use)\b", text) and not unsupported:
            reasons.append("ambiguous_request")
            fallback = clarification = True
        else:
            reasons.append("workspace_or_general")
    return RoutingDecision(
        tuple(sorted(domains | {"workspace"})), tuple(reasons), fallback, clarification
    )
