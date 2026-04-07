import os
import ast
from pathlib import Path

def extract_metadata_from_ast(file_path):
    """
    Parses a Python file using AST to find classes and their metadata
    without importing the module.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            tree = ast.parse(f.read())
        except Exception:
            return []

    drivers = []
    
    # 1. Detect if this file imports Digilent/mcculw (Heuristic for protocol)
    imports_digilent = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            if any('digilent' in name.lower() or 'mcculw' in name.lower() for name in names):
                imports_digilent = True

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            # We look for classes that have an AUTODETECT_ID
            # or appear to be Level 3 drivers (subclasses of something else)
            autodetect_id = None
            docstring = ast.get_docstring(node)
            
            # Check for AUTODETECT_ID in the class body
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id == 'AUTODETECT_ID':
                            if isinstance(item.value, ast.Constant):
                                autodetect_id = item.value.value
                            elif isinstance(item.value, ast.List):
                                # Handle list of strings
                                autodetect_id = ", ".join(str(el.value) for el in item.value.elts if hasattr(el, 'value'))
                            elif isinstance(item.value, (ast.Str, ast.Bytes)): # Legacy support
                                autodetect_id = item.value.s
            
            # Heuristic: Is it a candidate for a "Supported Instrument"?
            # Must have some bases (inheritance) and not be a base category class
            # We filter by looking for an AUTODETECT_ID OR a non-empty docstring
            # and ensuring it's not the name of the folder (Level 2 base)
            is_probably_l3 = (autodetect_id is not None)
            
            if is_probably_l3:
                # Infer Protocol/Binary
                protocol = "SCPI"
                binary_req = "NI-VISA"
                
                # Check bases for specialized reqs (Static analysis of base names)
                bases_text = str([ast.dump(b) for b in node.bases]).lower()
                if 'digilent' in bases_text or imports_digilent:
                    protocol = "Digilent VBS"
                    binary_req = "Requires mcculw"
                elif 'scpi' in bases_text:
                    protocol = "SCPI"
                elif 'instrument' not in bases_text:
                    protocol = "Custom Serial/Vendor"

                drivers.append({
                    'class_name': node.name,
                    'model': (docstring or "").split('\n')[0].strip() or autodetect_id or node.name,
                    'protocol': protocol,
                    'binary': binary_req
                })
                
    return drivers

def get_driver_info():
    drivers_root = Path(__file__).parent.parent.parent.parent / "src" / "piec" / "drivers"
    categories = {}
    
    # Exclude list
    exclude_folders = ['example', 'emulators', 'old', 'z_old', 'tests', '__pycache__']
    
    for folder in drivers_root.iterdir():
        if folder.is_dir() and folder.name not in exclude_folders and not folder.name.startswith('_'):
            category_name = folder.name.replace("_", " ").title()
            categories[category_name] = []
            
            for py_file in folder.glob("*.py"):
                # Skip __init__, base category files, and virtual drivers
                if py_file.name.startswith('__') or py_file.name == f"{folder.name}.py" or "virtual" in py_file.name:
                    continue
                
                try:
                    file_drivers = extract_metadata_from_ast(py_file)
                    for d in file_drivers:
                        # Construct module path
                        module_path = f"piec.drivers.{folder.name}.{py_file.stem}"
                        d['module'] = module_path
                        categories[category_name].append(d)
                except Exception:
                    continue
                    
    return categories

def generate_rst(categories):
    output = []
    output.append("Supported Instruments")
    output.append("=====================")
    output.append("")
    # Universal Requirements section
    output.append("Universal Requirements")
    output.append("----------------------")
    output.append("")
    output.append("* **NI-VISA**: Required for all standard VISA-based instruments.")
    output.append("* **NI-488.2**: Required for physical GPIB cards from National Instruments.")
    output.append("")
    output.append("Verified Versions")
    output.append("-----------------")
    output.append("")
    output.append("* **Python**: 3.8+")
    output.append("* **NI-VISA**: 2024+")
    output.append("* **OS**: Windows (Primary support)")
    output.append("")

    # Summary Table at the top
    output.append("Category Overview")
    output.append("-----------------")
    output.append("")
    output.append(".. list-table::")
    output.append("   :header-rows: 1")
    output.append("   :widths: 40 60")
    output.append("")
    output.append("   * - Category")
    output.append("     - Description")
    for cat_name, drivers in sorted(categories.items()):
        if not drivers: continue
        # Create a link-friendly target name
        link_target = cat_name.lower().replace(" ", "-")
        output.append(f"   * - :ref:`{cat_name} <{link_target}>`")
        # Extract a generic description or just count
        output.append(f"     - {len(drivers)} supported model{'s' if len(drivers) > 1 else ''}")
    output.append("")
    
    # Detailed Sections
    for cat_name, drivers in sorted(categories.items()):
        if not drivers:
            continue
        
        link_target = cat_name.lower().replace(" ", "-")
        output.append(f".. _{link_target}:")
        output.append("")
        output.append(cat_name)
        output.append("-" * len(cat_name))
        output.append("")
        output.append(f".. dropdown:: Click to view supported {cat_name} models")
        output.append("   :color: primary")
        output.append("   :icon: device-desktop")
        output.append("")
        output.append("   .. list-table::")
        output.append("      :header-rows: 1")
        output.append("      :widths: 30 25 20 25")
        output.append("")
        output.append("      * - Model / Description")
        output.append("        - Driver Class")
        output.append("        - Protocol")
        output.append("        - Requirements")
        
        for d in sorted(drivers, key=lambda x: x['model']):
            output.append(f"      * - {d['model']}")
            output.append(f"        - :py:class:`~{d['module']}.{d['class_name']}`")
            output.append(f"        - {d['protocol']}")
            output.append(f"        - {d['binary']}")
        output.append("")
        
    return "\n".join(output)

if __name__ == "__main__":
    # When running as a standalone or via exec() in conf.py
    data = get_driver_info()
    rst_content = generate_rst(data)
    
    # Target path relative to this script
    target_path = Path(__file__).parent.parent / "supported_instruments.rst"
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(rst_content)
    print(f"DONE: Generated instrument table at {target_path}")
