# Filebox: File Manager (Flask + SQLite)

    pip install -r requirements.txt
    python app.py
Open http://127.0.0.1:5000

- Upload (button or drag & drop, progress bar), 25 MB per file, 500 MB total
- Nested folders with breadcrumbs, rename, star, trash / restore / delete forever
- Search, sort, grid/list view, storage meter, preview (images, PDF, text), download
- Files saved on disk under random names in ./uploads; metadata in SQLite (files.db)
- Responsive layout, light print-friendly theme
