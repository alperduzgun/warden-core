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
    #[pyo3(get)]
    pub language: String,
}

fn detect_language_rs(path: &Path) -> String {
    let ext = path.extension()
        .and_then(|s| s.to_str())
        .map(|s| s.to_lowercase())
        .unwrap_or_default();
    
    match ext.as_str() {
        "py" | "pyw" => "python",
        "js" | "jsx" | "mjs" | "cjs" => "javascript",
        "ts" => "typescript",
        "tsx" => "tsx",
        "go" => "go",
        "rs" => "rust",
        "java" => "java",
        "dart" => "dart",
        "swift" => "swift",
        "kt" | "kts" => "kotlin",
        "c" => "c",
        "h" => "c", // Default to C, heuristic later
        "cpp" | "cc" | "cxx" | "hpp" | "hh" => "cpp",
        "cs" => "csharp",
        "rb" => "ruby",
        "php" => "php",
        "md" => "markdown",
        "yaml" | "yml" => "yaml",
        "json" => "json",
        "sql" => "sql",
        "sh" => "shell",
        _ => "unknown",
    }.to_string()
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
#[pyo3(signature = (root_path, use_gitignore=true, max_size_mb=None))]
fn discover_files(root_path: String, use_gitignore: bool, max_size_mb: Option<u64>) -> PyResult<Vec<(String, u64, String)>> {
    let mut files = Vec::new();
    let mut builder = WalkBuilder::new(&root_path);
    
    builder.standard_filters(use_gitignore)
           .hidden(false); 

    let warden_ignore = Path::new(&root_path).join(".wardenignore");
    if warden_ignore.exists() {
        builder.add_ignore(warden_ignore);
    }

    let walker = builder.build();

    // Default hard limit: 100MB if not specified, to prevent system freeze
    let size_limit_bytes = max_size_mb.unwrap_or(100) * 1024 * 1024;

    for result in walker {
        if let Ok(entry) = result {
            if entry.file_type().map_or(false, |ft| ft.is_file()) {
                let path = entry.path();
                
                // 1. Early Size Check (Fast metadata check)
                let size = entry.metadata().map(|m| m.len()).unwrap_or(0);
                if size > size_limit_bytes {
                    continue; // Skip huge files immediately
                }

                // 2. Early Binary Check (Read first 1024 bytes)
                if let Ok(mut file) = File::open(path) {
                    let mut buffer = [0; 1024];
                    let bytes_read = file.read(&mut buffer).unwrap_or(0);
                    if inspect(&buffer[..bytes_read]) == ContentType::BINARY {
                        continue; 
                    }
                }

                let path_str = path.to_string_lossy().to_string();
                let lang = detect_language_rs(path);
                files.push((path_str, size, lang));
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
            language: detect_language_rs(path),
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
pub struct AstNodeInfo {
    #[pyo3(get)]
    pub name: String,
    #[pyo3(get)]
    pub line_number: usize,
    #[pyo3(get)]
    pub code_snippet: String,
}

#[pyclass]
#[derive(Clone)]
pub struct AstMetadata {
    #[pyo3(get)]
    pub functions: Vec<AstNodeInfo>,
    #[pyo3(get)]
    pub classes: Vec<AstNodeInfo>,
    #[pyo3(get)]
    pub imports: Vec<AstNodeInfo>,
    #[pyo3(get)]
    pub references: Vec<String>,
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

// Queries for definitions and references
fn get_queries(lang: &str) -> (&str, &str, &str, &str) {
    match lang {
        "python" => (
            "(function_definition name: (identifier) @name)",
            "(class_definition name: (identifier) @name)",
            "(import_from_statement (dotted_name (identifier) @name)) (import_statement (dotted_name (identifier) @name))",
            "(identifier) @name" // Capture ALL identifiers as references
        ),
        "typescript" | "javascript" => (
            "(function_declaration name: (identifier) @name) (method_definition name: (property_identifier) @name)",
            "(class_declaration name: (type_identifier) @name)",
            "(import_statement (import_clause (named_imports (import_specifier name: (identifier) @name))))",
            "(identifier) @name"
        ),
         "go" => (
            "(function_declaration name: (identifier) @name) (method_declaration name: (field_identifier) @name)",
            "(type_declaration (type_spec name: (type_identifier) @name))",
            "(import_spec path: (interpreted_string_literal) @name)",
            "(identifier) @name"
        ),
        _ => ("", "", "", "") 
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
            references: vec![],
        });
    }

    parser.set_language(lang_parser.unwrap()).unwrap();
    let tree = parser.parse(&content, None).unwrap();
    let root_node = tree.root_node();
    
    let (func_q, class_q, imp_q, ref_q) = get_queries(&language);
    
    let process_query = |query_str: &str| -> Vec<AstNodeInfo> {
        let mut results = Vec::new();
        if query_str.is_empty() { return results; }
        
        if let Ok(query) = tree_sitter::Query::new(lang_parser.unwrap(), query_str) {
            let mut cursor = tree_sitter::QueryCursor::new();
            for m in cursor.matches(&query, root_node, content.as_bytes()) {
                for capture in m.captures {
                    if let Ok(text) = capture.node.utf8_text(content.as_bytes()) {
                        let start_line = capture.node.start_position().row + 1;
                        // Use parent for snippet context
                        let snippet = capture.node.parent()
                            .and_then(|p| p.utf8_text(content.as_bytes()).ok())
                            .unwrap_or(text)
                            .lines().next().unwrap_or(text).to_string(); // First line only
                        
                        let snippet = if snippet.len() > 200 { snippet[..200].to_string() + "..." } else { snippet.to_string() };

                        results.push(AstNodeInfo {
                            name: text.to_string(),
                            line_number: start_line,
                            code_snippet: snippet,
                        });
                    }
                }
            }
        }
        results
    };

    // Process references separately (simple string list)
    let mut references = Vec::new();
    if !ref_q.is_empty() {
        if let Ok(query) = tree_sitter::Query::new(lang_parser.unwrap(), ref_q) {
             let mut cursor = tree_sitter::QueryCursor::new();
             for m in cursor.matches(&query, root_node, content.as_bytes()) {
                for capture in m.captures {
                    if let Ok(text) = capture.node.utf8_text(content.as_bytes()) {
                        references.push(text.to_string());
                    }
                }
             }
        }
    }
    // Return all references (not deduped) to allow counting
    // references.sort();
    // references.dedup();

    Ok(AstMetadata {
        functions: process_query(func_q),
        classes: process_query(class_q),
        imports: process_query(imp_q),
        references
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

#[pyclass]
#[derive(Clone)]
pub struct MetricRule {
    #[pyo3(get, set)]
    pub id: String,
    #[pyo3(get, set)]
    pub metric_type: String, // "line_count", "size_bytes"
    #[pyo3(get, set)]
    pub threshold: u64,
}

#[pymethods]
impl MetricRule {
    #[new]
    fn new(id: String, metric_type: String, threshold: u64) -> Self {
        MetricRule { id, metric_type, threshold }
    }
}

#[pyclass]
#[derive(Clone)]
pub struct ValidationResult {
    #[pyo3(get)]
    pub rule_id: String,
    #[pyo3(get)]
    pub file_path: String,
    #[pyo3(get)]
    pub message: String,
    #[pyo3(get)]
    pub line: usize,
    #[pyo3(get)]
    pub snippet: String,
}

#[pyfunction]
fn validate_files(
    files: Vec<String>, 
    regex_rules: Vec<RustRule>, 
    metric_rules: Vec<MetricRule>
) -> PyResult<Vec<ValidationResult>> {
    
    // Compile regex rules
    let compiled_regexes: Vec<(String, Regex)> = regex_rules.into_iter()
        .filter_map(|r| Regex::new(&r.pattern).ok().map(|re| (r.id, re)))
        .collect();

    let results: Vec<ValidationResult> = files.par_iter()
        .flat_map(|path_str| {
            let path = Path::new(path_str);
            let mut file_results = Vec::new();

            // 1. Check Metadata Metrics (Fastest)
            if !metric_rules.is_empty() {
                if let Ok(metadata) = path.metadata() {
                    let size = metadata.len();
                    
                    // Size check
                    for rule in &metric_rules {
                        if rule.metric_type == "size_bytes" && size > rule.threshold {
                            file_results.push(ValidationResult {
                                rule_id: rule.id.clone(),
                                file_path: path_str.clone(),
                                message: format!("File size {} exceeds limit {}", size, rule.threshold),
                                line: 0,
                                snippet: String::new(),
                            });
                        }
                    }

                    // Line count check (requires reading, but avoiding regex)
                    let check_lines = metric_rules.iter().any(|r| r.metric_type == "line_count");
                    if check_lines {
                        if let Ok(file) = File::open(path) {
                            let reader = BufReader::new(file);
                            let line_count = reader.lines().count();
                             for rule in &metric_rules {
                                if rule.metric_type == "line_count" && line_count as u64 > rule.threshold {
                                    file_results.push(ValidationResult {
                                        rule_id: rule.id.clone(),
                                        file_path: path_str.clone(),
                                        message: format!("Line count {} exceeds limit {}", line_count, rule.threshold),
                                        line: 0,
                                        snippet: String::new(),
                                    });
                                }
                            }
                        }
                    }
                }
            }

            // 2. Check Regex Patterns (Slower)
            if !compiled_regexes.is_empty() {
                if let Ok(file) = File::open(path) {
                    let reader = BufReader::new(file);
                    for (ln, line_result) in reader.lines().enumerate() {
                        if let Ok(line) = line_result {
                            for (id, re) in &compiled_regexes {
                                if let Some(_m) = re.find(&line) {
                                    file_results.push(ValidationResult {
                                        rule_id: id.clone(),
                                        file_path: path_str.clone(),
                                        message: "Pattern match found".to_string(),
                                        line: ln + 1,
                                        snippet: line.trim().to_string(),
                                    });
                                }
                            }
                        }
                    }
                }
            }

            file_results
        })
        .collect();

    Ok(results)
}

#[pymodule]
fn warden_core_rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<AstMetadata>()?;
    m.add_class::<AstNodeInfo>()?;
    m.add_class::<RustRule>()?;
    m.add_class::<MetricRule>()?;
    m.add_class::<MatchHit>()?;
    m.add_class::<FileStats>()?;
    m.add_class::<ValidationResult>()?;
    m.add_function(wrap_pyfunction!(discover_files, m)?)?;
    m.add_function(wrap_pyfunction!(get_file_stats, m)?)?;
    m.add_function(wrap_pyfunction!(get_ast_metadata, m)?)?;
    m.add_function(wrap_pyfunction!(match_patterns, m)?)?;
    m.add_function(wrap_pyfunction!(validate_files, m)?)?;
    Ok(())
}
