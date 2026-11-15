For geometry creation only use create_geometry; for cut/fuse/intersect use
create_boolean_geometry. Do not create an unnecessary mesh job.
Use list_geometry_capabilities for supported primitives and parameters.
Use a real line for 1D and square, rectangle or disk for 2D, never a box for 2D.
A full 360 degree annulus is a 2D CSG cut: outer disk radius R minus concentric
inner disk radius r. Use inline disk operands in outer-then-inner order,
operation="cut", dimension=2. Do not substitute two unconnected disks or a cylinder.
Only inline primitive operands of the same 2D or 3D dimension are supported;
editing existing CAD artifacts by UUID is unavailable. Units must be explicit
where consequential. A submitted geometry is not yet the active completed one.
