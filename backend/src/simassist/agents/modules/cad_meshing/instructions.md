For uploaded STEP import AND meshing with explicit sizes, size units and matching
family call mesh_uploaded_geometry ONCE. It atomically queues import and dependent
mesh; do not also call import_uploaded_geometry or generate_mesh for the same
workflow. Ask for missing sizes/units/family before submission. Never infer mesh
size units from source CAD units, bounds or filenames.
