#!/usr/bin/env python3
"""
M6-B：PDF 零件目錄轉爆炸圖工具
將 PDF 每頁轉換為 PNG 圖片，供上傳至 dms.part.catalog.section

使用方式：
    pip install pymupdf
    python3 scripts/pdf_to_diagrams.py <PDF路徑> [輸出目錄] [--dpi 150]

輸出：
    每頁一個 PNG，命名為 001.png、002.png...
    同時產生 mapping.csv 供人工對應分區代號（E01、E02...）
"""

import argparse
import csv
import sys
from pathlib import Path


def convert_pdf(pdf_path: str, output_dir: str = None, dpi: int = 150):
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("錯誤：請先安裝 PyMuPDF：pip install pymupdf")
        sys.exit(1)

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        print(f"錯誤：找不到檔案 {pdf_path}")
        sys.exit(1)

    if output_dir is None:
        output_dir = pdf_path.parent / pdf_path.stem
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    total = len(doc)
    print(f"PDF 共 {total} 頁，開始轉換（解析度 {dpi} DPI）...")

    mat = fitz.Matrix(dpi / 72, dpi / 72)
    mapping_rows = []

    for i, page in enumerate(doc):
        page_num = i + 1
        img_name = f"{page_num:03d}.png"
        img_path = output_dir / img_name
        pix = page.get_pixmap(matrix=mat)
        pix.save(str(img_path))
        size_kb = img_path.stat().st_size // 1024
        print(f"  頁 {page_num:3d}/{total} → {img_name} ({size_kb} KB)")
        mapping_rows.append({
            'page': page_num,
            'image_file': img_name,
            'section_code': '',   # 人工填入，如 E01
            'section_name': '',   # 人工填入，如 蓋蓋
            'category': '',       # 人工填入：engine 或 frame
        })

    doc.close()

    # 輸出 mapping CSV 供人工對應
    mapping_path = output_dir / 'mapping.csv'
    with open(mapping_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=['page', 'image_file', 'section_code', 'section_name', 'category'])
        writer.writeheader()
        writer.writerows(mapping_rows)

    print(f"\n完成！圖片輸出至：{output_dir}/")
    print(f"請開啟 {mapping_path} 填入 section_code / section_name / category")
    print("填完後即可至 Odoo「零件目錄」→ 對應分區上傳爆炸圖")


def main():
    parser = argparse.ArgumentParser(description='PDF 零件目錄轉爆炸圖工具')
    parser.add_argument('pdf', help='PDF 檔案路徑')
    parser.add_argument('output', nargs='?', default=None, help='輸出目錄（預設：同 PDF 目錄下同名資料夾）')
    parser.add_argument('--dpi', type=int, default=150, help='解析度（預設 150 DPI）')
    args = parser.parse_args()
    convert_pdf(args.pdf, args.output, args.dpi)


if __name__ == '__main__':
    main()
