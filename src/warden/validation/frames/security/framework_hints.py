"""Framework-aware security hints for LLM prompt augmentation.

When the project intelligence detects a specific framework, these hints
are appended to the semantic context to guide the LLM toward framework-specific
vulnerability patterns and reduce false positives.
"""

# Map of framework name (lowercase) to security-relevant hints.
# Keys are matched with substring against detected_frameworks string.
FRAMEWORK_SECURITY_HINTS: dict[str, str] = {
    "flask": (
        "Flask: render_template_string() is SSTI-vulnerable. "
        "redirect(request.args['next']) is open-redirect. "
        "@app.route without methods= accepts ALL HTTP methods. "
        "Flask does NOT have CSRF protection by default (need flask-wtf)."
    ),
    "django": (
        "Django: ORM is parameterized by default (reduce SQL injection FPs). "
        "mark_safe() and |safe template filter disable auto-escaping (XSS). "
        "ALLOWED_HOSTS=[] means host header injection. "
        "Model(**request.data) without fields= is mass assignment."
    ),
    "fastapi": (
        "FastAPI: Pydantic validates input by default (reduce mass assignment FPs). "
        "Response(content=user_input) is XSS if returning text/html. "
        "Depends() injection is safe. BackgroundTasks can leak request state."
    ),
    "express": (
        "Express: res.redirect(req.query.url) is open-redirect. "
        "express.static() path traversal if symlinks not disabled. "
        "No CSRF protection by default (need csurf/helmet). "
        "body-parser has no size limit by default (DoS)."
    ),
    "spring": (
        "Spring: @ModelAttribute + @RequestBody = mass assignment risk. "
        "@CrossOrigin(\"*\") disables CORS protection. "
        "ObjectMapper.enableDefaultTyping() = deserialization RCE. "
        "Spring Security CSRF is ON by default (don't flag if enabled)."
    ),
    "gin": (
        "Gin: c.ShouldBind(&obj) is mass assignment if obj has sensitive fields. "
        "c.String/c.HTML with user input is XSS. "
        "gin.Default() includes Logger and Recovery middleware."
    ),
    "nextjs": (
        "Next.js: getServerSideProps/getStaticProps run server-side (not client). "
        "API routes in /api are server-side only. "
        "dangerouslySetInnerHTML is XSS. "
        "Middleware runs at the edge — different security context."
    ),
    "sveltekit": (
        "SvelteKit: +page.server.ts load functions are server-side. "
        "{@html content} is XSS (unescaped HTML). "
        "Form actions handle CSRF automatically. "
        "hooks.server.ts handles auth — check it exists."
    ),
    "rails": (
        "Rails: ActiveRecord is parameterized by default (reduce SQL FPs). "
        "params.permit() is mass assignment protection — flag if missing. "
        "html_safe and raw() disable escaping (XSS). "
        "protect_from_forgery handles CSRF — check if skipped."
    ),
    "laravel": (
        "Laravel: Eloquent is parameterized by default. "
        "DB::raw() and whereRaw() bypass parameterization (SQL injection). "
        "{!! $var !!} disables Blade escaping (XSS). "
        "CSRF middleware is ON by default."
    ),
    "flutter": (
        "Flutter/Dart: http package does NOT pin certificates by default. "
        "SharedPreferences stores data in plaintext on device. "
        "WebView.loadUrl with user input is open-redirect. "
        "Platform channels can expose native API to Dart."
    ),
    "fastmcp": (
        "FastMCP server detected. Security-critical configuration: "
        "TransportSecuritySettings(enable_dns_rebinding_protection=False) disables DNS rebinding protection — flag as HIGH. "
        "FastMCP(transport='http') with host='0.0.0.0' exposes to all interfaces — verify auth middleware exists. "
        "Credentials accepted via request headers (e.g. request.headers.get('x-*-private-key')) bypass standard auth — flag as HIGH. "
        "mcp.run() without TransportSecuritySettings uses defaults — verify enable_dns_rebinding_protection=True. "
        "HTTP transport requires CredentialsMiddleware or equivalent authentication before tool execution."
    ),
    "mcp": (
        "MCP (Model Context Protocol) server detected. "
        "MCP servers expose tools to AI agents — input validation on all tool arguments is critical. "
        "Transport security settings must be explicitly configured (DNS rebinding protection, binding interface). "
        "Any sensitive credentials passed through tool call arguments or request headers should be flagged. "
        "stdio transport is safer than http transport — http transport requires additional auth middleware."
    ),
}


def get_framework_hints(detected_frameworks: str) -> str:
    """Return concatenated security hints for detected frameworks."""
    if not detected_frameworks:
        return ""
    lower = detected_frameworks.lower()
    hints = []
    for framework, hint in FRAMEWORK_SECURITY_HINTS.items():
        if framework in lower:
            hints.append(hint)
    return "\n".join(hints)
