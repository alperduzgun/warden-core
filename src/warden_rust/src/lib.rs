use pyo3::prelude::*;
use ignore::WalkBuilder;
use std::path::Path;
use std::fs::File;
use regex::Regex;
use rayon::prelude::*;
use std::io::{BufRead, BufReader, Read};
use sha2::{Sha256, Digest};
use content_inspector::{inspect, ContentType};

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
pub struct FileStats {
    #[pyo3(get)]
    pub path: String,
    #[pyo3(get)]
    pub size: u64,
    #[pyo3(get)]
    pub line_count: usize,
    #[pyo3(get)]
    pub is_binary: bool,
    #[pyo3(get)]
    pub hash: String,
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
fn get_file_stats(paths: Vec<String>) -> PyResult<Vec<FileStats>> {
    let stats: Vec<FileStats> = paths.par_iter().map(|path_str| {
        let path = Path::new(path_str);
        let mut stats = FileStats {
            path: path_str.clone(),
            size: 0,
            line_count: 0,
            is_binary: false,
            hash: String::new(),
        };

        if let Ok(metadata) = path.metadata() {
            stats.size = metadata.len();
        }

        if let Ok(mut file) = File::open(path) {
            // Read first 1024 bytes for binary check
            let mut buffer = [0; 1024];
            let bytes_read = file.read(&mut buffer).unwrap_or(0);
            stats.is_binary = inspect(&buffer[..bytes_read]) == ContentType::BINARY;

            if !stats.is_binary {
                // Return to start for hash and line count
                // Re-open/seek might be expensive, but line counting is necessary
                // For simplicity, we'll re-read everything.
                if let Ok(file_reopen) = File::open(path) {
                    let reader = BufReader::new(file_reopen);
                    let mut line_count = 0;
                    let mut hasher = Sha256::new();
                    
                    for line_result in reader.lines() {
                        if let Ok(line) = line_result {
                            line_count += 1;
                            hasher.update(line.as_bytes());
                            hasher.update(b"\n");
                        }
                    }
                    stats.line_count = line_count;
                    stats.hash = format!("{:x}", hasher.finalize());
                }
            } else {
                // For binary, just do a fast whole-file hash if small
                if stats.size < 50_000_000 { // 50MB limit for full hash
                    if let Ok(mut file_reopen) = File::open(path) {
                        let mut hasher = Sha256::new();
                        let mut buffer = Vec::new();
                        if file_reopen.read_to_end(&mut buffer).is_ok() {
                            hasher.update(&buffer);
                            stats.hash = format!("{:x}", hasher.finalize());
                        }
                    }
                }
            }
        }
        stats
    }).collect();

    Ok(stats)
}

#[pyclass]
#[derive(Clone)]
pub struct AstMetadata {
    #[pyo3(get)]
    pub functions: Vec<String>,
    #[pyo3(get)]
    pub classes: Vec<String>,
    #[pyo3(get)]
    pub imports: Vec<String>,
}

fn get_language_parser(lang: &str) -> Option<tree_sitter::Language> {
    match lang {
        "python" => Some(tree_sitter_python::language()),
        "typescript" => Some(tree_sitter_typescript::language_typescript()),
        "javascript" => Some(tree_sitter_javascript::language()),
        "go" => Some(tree_sitter_go::language()),
        "java" => Some(tree_sitter_java::language()),
        _ => None,
    }
}

// Queries for extracting definitions
fn get_queries(lang: &str) -> (&str, &str, &str) {
    match lang {
        "python" => (
            "(function_definition name: (identifier) @name)",
            "(class_definition name: (identifier) @name)",
            "(import_from_statement (dotted_name (identifier) @name)) (import_statement (dotted_name (identifier) @name))"
        ),
        "typescript" | "javascript" => (
            "(function_declaration name: (identifier) @name) (method_definition name: (property_identifier) @name)",
            "(class_declaration name: (type_identifier) @name)",
            "(import_statement (import_clause (named_imports (import_specifier name: (identifier) @name))))"
        ),
         "go" => (
            "(function_declaration name: (identifier) @name) (method_declaration name: (field_identifier) @name)",
            "(type_declaration (type_spec name: (type_identifier) @name))",
            "(import_spec path: (interpreted_string_literal) @name)"
        ),
        _ => ("", "", "") // TODO: Add others
    }
}

#[pyfunction]
fn get_ast_metadata(content: String, language: String) -> PyResult<AstMetadata> {
    let mut parser = tree_sitter::Parser::new();
    let lang_parser = get_language_parser(&language);
    
    if lang_parser.is_none() {
        return Ok(AstMetadata {
            functions: vec![],
            classes: vec![],
            imports: vec![],
        });
    }

    parser.set_language(lang_parser.unwrap()).unwrap();
    let tree = parser.parse(&content, None).unwrap();
    let root_node = tree.root_node();
    
    let (func_q, class_q, imp_q) = get_queries(&language);
    
    let mut functions = Vec::new();
    let mut classes = Vec::new();
    let mut imports = Vec::new();

    // Helper to execute query and collect captures
    // Note: In a real impl we'd compile these once. Here we do it ad-hoc for simplicity in this iteration.
    if let Ok(query) = tree_sitter::Query::new(lang_parser.unwrap(), func_q) {
        let mut cursor = tree_sitter::QueryCursor::new();
        for m in cursor.matches(&query, root_node, content.as_bytes()) {
            for capture in m.captures {
                if let Ok(text) = capture.node.utf8_text(content.as_bytes()) {
                     functions.push(text.to_string());
                }
            }
        }
    }

    if let Ok(query) = tree_sitter::Query::new(lang_parser.unwrap(), class_q) {
        let mut cursor = tree_sitter::QueryCursor::new();
        for m in cursor.matches(&query, root_node, content.as_bytes()) {
             for capture in m.captures {
                if let Ok(text) = capture.node.utf8_text(content.as_bytes()) {
                     classes.push(text.to_string());
                }
            }
        }
    }

    // Imports (Simplified)
    if let Ok(query) = tree_sitter::Query::new(lang_parser.unwrap(), imp_q) {
        let mut cursor = tree_sitter::QueryCursor::new();
         for m in cursor.matches(&query, root_node, content.as_bytes()) {
             for capture in m.captures {
                if let Ok(text) = capture.node.utf8_text(content.as_bytes()) {
                     imports.push(text.to_string());
                }
            }
        }
    }

    Ok(AstMetadata {
        functions,
        classes,
        imports
    })
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
    m.add_class::<AstMetadata>()?;
    m.add_class::<RustRule>()?;
    m.add_class::<MatchHit>()?;
    m.add_class::<FileStats>()?;
    m.add_function(wrap_pyfunction!(discover_files, m)?)?;
    m.add_function(wrap_pyfunction!(get_file_stats, m)?)?;
    m.add_function(wrap_pyfunction!(get_ast_metadata, m)?)?;
    m.add_function(wrap_pyfunction!(match_patterns, m)?)?;
    Ok(())
}
