# SimAssist - Codex Instructions

## Project Overview

SimAssist is a local AI-powered numerical simulation platform.

Technology stack:
- Backend: Python, FastAPI, Microsoft Agent Framework
- LLM: Local models through LM Studio, optional remote providers
- Geometry and Meshing: Gmsh
- Numerical Solvers: CalculiX, Code_Aster (planned)
- Frontend: React, Vite, VTK.js
- Package Management: uv

## Coding Principles

- Follow the installed karpathy-guidelines skill.
- Think before coding.
- Prefer simple, maintainable solutions.
- Make minimal and surgical changes.
- Reuse existing implementations.
- Avoid unnecessary abstractions.
- Do not refactor unrelated code.
- Preserve existing functionality.

## Skill Usage

Use installed skills selectively based on the task.

### Backend
- karpathy-guidelines
- code-review
- diagnosing-bugs
- tdd

### Frontend
- ui-ux-pro-max
- ui-styling
- design-system

### Architecture
- codebase-design
- improve-codebase-architecture

### Planning
- research
- to-spec
- implement

Do not activate every skill automatically.
Only use skills relevant to the current task.

## Simulation Rules

- Preserve existing geometry and meshing functionality.
- Validate geometry before meshing.
- Verify mesh generation and mesh validity.
- Do not claim solver results are correct without verification.
- Keep numerical units consistent.
- Avoid hardcoded geometry-specific assumptions.

## LLM and Agent Rules

- Preserve local LLM support.
- Keep LLM providers interchangeable.
- Log tool execution and errors.
- Do not introduce unnecessary agent complexity.
- Avoid unnecessary LLM calls.

## Testing

- Run tests relevant to modified code.
- Do not run unrelated benchmarks.
- Avoid repeatedly executing the same tests.
- Report tests that could not be executed.
- Never claim tests passed unless executed.

## Workflow

1. Inspect relevant files.
2. Identify the smallest necessary change.
3. Implement the change.
4. Run focused verification.
5. Summarize modifications and test results.
