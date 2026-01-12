use pyo3::prelude::*;
use ignore::WalkBuilder;
use std::path::Path;

#[pyfunction]
#[pyo3(signature = (root_path, use_gitignore=true))]
fn discover_files(root_path: String, use_gitignore: bool) -> PyResult<Vec<(String, u64)>> {
    let mut files = Vec::new();
    let mut builder = WalkBuilder::new(&root_path);
    
    builder.standard_filters(use_gitignore)
           .hidden(false); // Warden includes hidden files like .claude.json

    // Add .wardenignore if it exists
    let warden_ignore = Path::new(&root_path).join(".wardenignore");
    if warden_ignore.exists() {
        builder.add_ignore(warden_ignore);
    }

    let walker = builder.build();

    for result in walker {
        match result {
            Ok(entry) => {
                if entry.file_type().map_or(false, |ft| ft.is_file()) {
                    let path = entry.path().to_string_lossy().to_string();
                    let metadata = entry.metadata().ok();
                    let size = metadata.map(|m| m.len()).unwrap_or(0);
                    files.push((path, size));
                }
            }
            Err(_err) => {}
        }
    }
    Ok(files)
}

#[pymodule]
fn warden_core_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(discover_files, m)?)?;
    Ok(())
}
