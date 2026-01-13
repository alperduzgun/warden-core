import os
import ast
import re
from pathlib import Path

# Target methods extracted from SARIF
TARGET_METHODS = {
    "_add_suppression", "_analyze_cleanup", "_analyze_file", "_analyze_file_contexts",
    "_analyze_project_structure", "_analyze_project_with_llm", "_analyze_results",
    "_analyze_single_file", "_analyze_with_llm", "_apply_fortification", "_call_llm",
    "_call_llm_batch", "_call_llm_with_retry", "_check_suppression", "_check_symbol",
    "_check_syntax", "_classify_code", "_clear_index", "_convert_to_code_files",
    "_create_baseline", "_create_discovery_canvas", "_detect_frameworks", "_discover_files",
    "_discover_files_phase", "_enhance_suggestions_with_llm", "_execute_builtin",
    "_execute_fix", "_execute_frame_with_rules", "_execute_frames_fail_fast",
    "_execute_frames_parallel", "_execute_frames_sequential", "_execute_get_config",
    "_execute_list_frames", "_execute_pipeline", "_execute_pipeline_stream",
    "_execute_rules", "_execute_scan", "_execute_tool", "_generate_html_report",
    "_generate_json_report", "_generate_pdf_report", "_get_all_issues",
    "_get_available_frames", "_get_available_models", "_get_available_providers",
    "_get_cleanup_score", "_get_cleanup_suggestions", "_get_configuration",
    "_get_files_by_type", "_get_fortification_suggestions", "_get_frame_stats",
    "_get_index_stats", "_get_issue_by_hash", "_get_issue_history", "_get_issue_stats",
    "_get_open_issues", "_get_project_stats", "_get_quality_score", "_get_report_status",
    "_get_security_score", "_get_server_status", "_get_severity_stats",
    "_get_suppressions", "_get_trends", "_handle_initialize", "_handle_initialized",
    "_handle_ping", "_handle_request", "_handle_request_with_writer",
    "_handle_resources_list", "_handle_resources_read", "_handle_streaming_method",
    "_handle_tools_call", "_handle_tools_list", "_health_check",
    "_identify_impacted_files", "_index_project", "_initialize_llm_analyzer",
    "_load_build_context_phase", "_load_from_directory", "_load_single_file",
    "_process_message", "_read_loop", "_refill", "_remove_suppression",
    "_reopen_issue", "_resolve_issue", "_run_socket", "_run_stdio",
    "_save_context_to_memory", "_search_by_description", "_search_code",
    "_search_similar_code", "_select_frames_for_project", "_suppress_issue",
    "_test_llm_provider", "_tool_list_reports", "_tool_status", "_update_configuration",
    "_update_frame_status", "_validate_ai_rule", "_validate_llm_config",
    "_validate_script", "_verify_build", "_watch_report_file", "_write_message",
    "acquire", "analyze", "analyze_batch", "analyze_batch_with_llm",
    "analyze_code_quality", "analyze_file_context", "analyze_project_structure",
    "analyze_with_llm", "build_graph", "classify_and_select_frames", "delete_issue",
    "enhance_with_llm", "execute", "execute_batch", "execute_pipeline",
    "execute_pipeline_stream", "execute_safe", "execute_single_file",
    "execute_with_discovery", "execute_with_llm", "execute_with_semaphore",
    "execute_with_weights", "generate_batch_fortifications",
    "generate_batch_suggestions", "generate_cleaning_suggestions",
    "generate_fortification", "generate_suppression_rules", "get_all_issues",
    "get_available_frames", "get_available_providers", "get_client", "get_config",
    "get_issue", "get_universal_ast", "handle_client", "initialize",
    "learn_from_feedback", "load_from_file", "load_from_repositories", "main",
    "ping", "request_fix", "run_indexing_if_files_exist", "run_ipc_server",
    "save_file_states", "save_issue", "scan", "send_notification", "send_request",
    "shutdown", "shutdown_all", "start", "stop", "stream_completion",
    "update_frame_status", "wait_for_termination"
}

RENAME_MAP = {name: f"{name}_async" for name in TARGET_METHODS if not name.endswith("_async")}

def refactor_file(file_path):
    with open(file_path, 'r') as f:
        content = f.read()

    new_content = content
    for old_name, new_name in RENAME_MAP.items():
        # 1. Update definitions
        new_content = re.sub(fr"(async\s+def\s+)({old_name})(\()", fr"\1{new_name}\3", new_content)
        
        # 2. Update call sites and imports
        # Word boundary \b is key here to avoid partial matches
        
        # await name(
        new_content = re.sub(fr"(await\s+)(\b{old_name}\b)(\()", fr"\1{new_name}\3", new_content)
        
        # await obj.name(
        new_content = re.sub(fr"(await\s+[\w\.]+\.)(\b{old_name}\b)(\()", fr"\1{new_name}\3", new_content)
        
        # asyncio.run(name(...))
        new_content = re.sub(fr"(asyncio\.run\()(\b{old_name}\b)(\()", fr"\1{new_name}\3", new_content)
        
        # from module import name
        new_content = re.sub(fr"(from\s+[\w\.]+\s+import\s+)(\b{old_name}\b)(\s+as\b|\s*|$)", fr"\1{new_name}\3", new_content, flags=re.MULTILINE)
        
        # import name
        new_content = re.sub(fr"(\bimport\s+)(\b{old_name}\b)(\s+as\b|\s*|$)", fr"\1{new_name}\3", new_content, flags=re.MULTILINE)

        # Attribute access not covered by await (e.g. self.name())
        new_content = re.sub(fr"(\.)(\b{old_name}\b)(\()", fr"\1{new_name}\3", new_content)
        
        # asyncio.run(obj.name())
        new_content = re.sub(fr"(asyncio\.run\([\w\.]+\.)(\b{old_name}\b)(\()", fr"\1{new_name}\3", new_content)

    if new_content != content:
        with open(file_path, 'w') as f:
            f.write(new_content)
        return True
    return False

def main():
    base_dirs = [Path("src/warden"), Path("tests")]
    files_changed = 0
    
    for base_dir in base_dirs:
        for py_file in base_dir.rglob("*.py"):
            if refactor_file(py_file):
                print(f"Refactor applied to: {py_file}")
                files_changed += 1
            
    print(f"\nTotal files changed: {files_changed}")

if __name__ == "__main__":
    main()
