For creating geometry AND mesh use create_geometry_and_mesh, or
create_boolean_geometry_and_mesh for Boolean CSG. Each submits one dependency-aware
workflow. Do not separately call create_geometry and generate_mesh for that same
combined request. Meshing waits for verified geometry completion.
