import os
# Hide the Hugging Face symlink warnings
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions

# 1. Configure the Memory Guard Pipeline Options
pipeline_options = PdfPipelineOptions()
pipeline_options.do_ocr = False       # Crucial: Drops RAM consumption instantly
pipeline_options.images_scale = 1.0   # Scale factor for generated images (1.0 is standard quality)

# 2. Instantiate the converter with our explicit PDF format binding
converter = DocumentConverter(
    allowed_formats=[InputFormat.PDF],
    format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
    }
)

print("⏳ Processing 'regulations.pdf' safely within memory bounds...")
result = converter.convert("regulations.pdf")

doc = result.document
markdown = doc.export_to_markdown()
print("✨ PDF fully converted without crashing!")
