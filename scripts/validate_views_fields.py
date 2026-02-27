#!/usr/bin/env python3
"""Validate XML view fields exist in model python definitions.

Usage: python scripts/validate_views_fields.py
"""
import re
import os
import sys
import ast
from xml.etree import ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(__file__))
ADDON_PATH = os.path.join(ROOT, 'addons', 'dms_core')


def find_view_fields(view_path):
    tree = ET.parse(view_path)
    root = tree.getroot()
    fields = set()
    # Find fields only inside view arch content (e.g., <form>, <tree>, <search>)
    for view_tag in ('form', 'tree', 'search', 'kanban', 'calendar', 'pivot'):
        for parent in root.findall('.//' + view_tag):
            for field in parent.findall('.//field'):
                name = field.get('name')
                if name:
                    fields.add(name)
    return fields


def find_model_fields(model_path):
    # Use AST parsing to robustly find assignments to fields.<Type>(...),
    # which supports multi-line declarations and string literals containing newlines.
    with open(model_path, 'r', encoding='utf-8') as f:
        source = f.read()
    tree = ast.parse(source, filename=model_path)
    fields = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            # single or multiple targets
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name = target.id
                else:
                    continue
                val = node.value
                # check for fields.<Type>(...)
                if isinstance(val, ast.Call) and isinstance(val.func, ast.Attribute):
                    func = val.func
                    if isinstance(func.value, ast.Name) and func.value.id == 'fields':
                        fields.add(name)
    return fields


def main():
    views_dir = os.path.join(ADDON_PATH, 'views')
    models_dir = os.path.join(ADDON_PATH, 'models')
    model_file = os.path.join(models_dir, 'dealer.py')

    if not os.path.exists(model_file):
        print('Model file not found:', model_file)
        sys.exit(2)

    # aggregate fields from all views under addon
    view_fields = set()
    for fname in os.listdir(views_dir):
        if not fname.endswith('.xml'):
            continue
        path = os.path.join(views_dir, fname)
        view_fields |= find_view_fields(path)

    model_fields = find_model_fields(model_file)

    missing = sorted([f for f in view_fields if f not in model_fields])

    print('Fields found in views:', len(view_fields))
    print(sorted(view_fields))
    print('Fields found in model:', len(model_fields))
    print(sorted(model_fields))
    if missing:
        print('\nMissing fields (referenced in views but not in model):')
        for f in missing:
            print('-', f)
        sys.exit(1)
    else:
        print('\nAll view fields are present in the model.')


if __name__ == '__main__':
    main()
