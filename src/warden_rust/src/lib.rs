use pyo3::prelude::*;
use ignore::WalkBuilder;
use std::path::Path;
use regex::Regex;
use rayon::prelude::*;
use std::fs::File;
use std::io::{BufRead, BufReader};

#[pyclass]
#[derive(Clone)]
pub struct RustRule {
    #[pyo3(get, set)]
    pub id: String,
    #[pyo3(get, set)]
    pub pattern: String,
}

#[pymethods]
impl RustRule {
    #[new]
    fn new(id: String, pattern: String) -> Self {
        RustRule { id, pattern }
    }
}

#[pyclass]
#[derive(Clone)]
pub struct MatchHit {
    #[pyo3(get)]
    pub file_path: String,
    #[pyo3(get)]
    pub line_number: usize,
    #[pyo3(get)]
    pub column: usize,
    #[pyo3(get)]
    pub rule_id: String,
    #[pyo3(get)]
    pub snippet: String,
}

#[pyfunction]
#[pyo3(signature = (root_path, use_gitignore=true))]
fn discover_files(root_path: String, use_gitignore: bool) -> PyResult<Vec<(String, u64)>> {
    let mut files = Vec::new();
    let mut builder = WalkBuilder::new(&root_path);
    
    builder.standard_filters(use_gitignore)
           .hidden(false); 

    let warden_ignore = Path::new(&root_path).join(".wardenignore");
    if warden_ignore.exists() {
        builder.add_ignore(warden_ignore);
    }

    let walker = builder.build();

    for result in walker {
        if let Ok(entry) = result {
            if entry.file_type().map_or(false, |ft| ft.is_file()) {
                let path = entry.path().to_string_lossy().to_string();
                let size = entry.metadata().map(|m| m.len()).unwrap_or(0);
                files.push((path, size));
            }
        }
    }
    Ok(files)
}

#[pyfunction]
fn match_patterns(files: Vec<String>, rules: Vec<RustRule>) -> PyResult<Vec<MatchHit>> {
    // Compile regexes once
    let compiled_rules: Vec<(String, Regex)> = rules.into_iter()
        .filter_map(|r| {
            Regex::new(&r.pattern).ok().map(|re| (r.id, re))
        })
        .collect();

    if compiled_rules.is_empty() {
        return Ok(Vec::new());
    }

    // Process files in parallel
    let hits: Vec<MatchHit> = files.par_iter()
        .flat_map(|file_path| {
            let mut file_hits = Vec::new();
            if let Ok(file) = File::open(file_path) {
                let reader = BufReader::new(file);
                for (ln, line_result) in reader.lines().enumerate() {
                    if let Ok(line) = line_result {
                        for (id, re) in &compiled_rules {
                            if let Some(m) = re.find(&line) {
                                file_hits.push(MatchHit {
                                    file_path: file_path.clone(),
                                    line_number: ln + 1,
                                    column: m.start() + 1,
                                    rule_id: id.clone(),
                                    snippet: line.trim().to_string(),
                                });
                                // We found a match for this rule on this line, stop checking this rule for this line
                                // (Actually, we might want multiple rules for the same line, but maybe one hit per rule per line is enough)
                            }
                        }
                    }
                }
            }
            file_hits
        })
        .collect();

    Ok(hits)
}

#[pymodule]
fn warden_core_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RustRule>()?;
    m.add_class::<MatchHit>()?;
    m.add_function(wrap_pyfunction!(discover_files, m)?)?;
    m.add_function(wrap_pyfunction!(match_patterns, m)?)?;
    Ok(())
}
