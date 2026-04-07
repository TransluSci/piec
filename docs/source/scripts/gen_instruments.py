import os
import ast
from pathlib import Path

def clean_model_name(name):
    """
    Strips 'Driver for the', 'Specific Class for', etc.
    to leave just the model name for the documentation table.
    """
    prefixes = [
        "Driver for the ",
        "Driver for ",
        "Specific Class for the ",
        "Specific Class for this exact model of ",
        "Specific Class for ",
        "Specific of the ",
        "Specific class for ",
        "MODEL "
    ]
    
    cleaned = name.strip()
    for p in prefixes:
        if cleaned.lower().startswith(p.lower()):
            cleaned = cleaned[len(p):]
            break
            
    # Remove trailing periods and extra whitespace
    return cleaned.strip().rstrip('.')

def extract_metadata_from_ast(file_path, valid_bases):
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
    
    # Pre-calculate lowercase versions for easier matching
    valid_bases_lower = [b.lower() for b in valid_bases]
    
    # 1. Detect if this file imports Digilent/mcculw (Heuristic for protocol)
    imports_digilent = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            if any('digilent' in name.lower() or 'mcculw' in name.lower() for name in names):
                imports_digilent = True

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            # To be a driver, it must inherit from a known Base (Instrument, Scpi, AWG, etc.)
            # and not be the base definition itself.
            is_base_definition = node.name in valid_bases
            
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
                                autodetect_id = ", ".join(str(el.value) for el in item.value.elts if hasattr(el, 'value'))
                            elif isinstance(item.value, (ast.Str, ast.Bytes)):
                                autodetect_id = item.value.s
            
            # Inherits from a known base?
            inherited_from_core = False
            for base in node.bases:
                b_name = base.id if isinstance(base, ast.Name) else base.attr if isinstance(base, ast.Attribute) else ""
                if b_name.lower() in valid_bases_lower:
                    inherited_from_core = True
                    break

            is_probably_l3 = (autodetect_id is not None or inherited_from_core) and not is_base_definition
            
            if is_probably_l3:
                # Infer Protocol/Binary
                protocol = "SCPI"
                binary_req = "NI-VISA"
                
                # Check bases for specialized reqs
                bases_text = str([ast.dump(b) for b in node.bases]).lower()
                if 'digilent' in bases_text or imports_digilent:
                    protocol = "Digilent VBS"
                    binary_req = "Requires mcculw"
                elif 'scpi' in bases_text:
                    protocol = "SCPI"
                elif 'instrument' not in bases_text:
                    protocol = "Custom Serial/Vendor"

                raw_model = (docstring or "").split('\n')[0].strip() or autodetect_id or node.name
            
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

                raw_model = (docstring or "").split('\n')[0].strip() or autodetect_id or node.name
                
                drivers.append({
                    'class_name': node.name,
                    'model': clean_model_name(raw_model),
                    'protocol': protocol,
                    'binary': binary_req
                })
                
    return drivers

def get_driver_info():
    drivers_root = Path(__file__).parent.parent.parent.parent / "src" / "piec" / "drivers"
    categories = {}
    
    # 1. Discover Global Base Classes (instrument.py, scpi.py, virtual_instrument.py)
    global_bases = set(['Instrument', 'Scpi', 'VirtualInstrument', 'Digilent'])
    for base_file in ['instrument.py', 'scpi.py', 'virtual_instrument.py', 'digilent.py']:
        path = drivers_root / base_file
        if path.exists():
            with open(path, "r") as f:
                try:
                    tree = ast.parse(f.read())
                    for node in tree.body:
                        if isinstance(node, ast.ClassDef):
                            global_bases.add(node.name)
                except: pass

    # Exclude list
    exclude_folders = ['example', 'emulators', 'old', 'z_old', 'tests', '__pycache__']
    
    for folder in drivers_root.iterdir():
        if folder.is_dir() and folder.name not in exclude_folders and not folder.name.startswith('_'):
            category_name = folder.name.replace("_", " ").title()
            categories[category_name] = []
            
            # 2. Find Category-Specific Base Classes (e.g. dmm/dmm.py)
            category_bases = set(global_bases)
            base_file = folder / f"{folder.name}.py"
            if base_file.exists():
                with open(base_file, "r") as f:
                    try:
                        tree = ast.parse(f.read())
                        for node in tree.body:
                            if isinstance(node, ast.ClassDef):
                                category_bases.add(node.name)
                    except: pass
            
            for py_file in folder.glob("*.py"):
                # Skip __init__, base category files, and virtual drivers
                if py_file.name.startswith('__') or py_file.name == f"{folder.name}.py" or "virtual" in py_file.name:
                    continue
                
                try:
                    file_drivers = extract_metadata_from_ast(py_file, category_bases)
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
