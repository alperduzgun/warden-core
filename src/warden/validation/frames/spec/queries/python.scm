; Python tree-sitter queries for FastAPI contract extraction
; Used by FastAPIExtractor for precise AST-based extraction

; ============================================
; Route Decorators
; ============================================

; @app.get("/users")
; @router.post("/users")
(decorated_definition
  (decorator
    (call
      function: (attribute
        object: (identifier) @router_name
        attribute: (identifier) @http_method
        (#match? @http_method "^(get|post|put|patch|delete)$")
      )
      arguments: (argument_list
        (string) @route_path
      )
    )
  ) @route_decorator
  definition: (function_definition
    name: (identifier) @func_name
    parameters: (parameters) @params
    return_type: (type)? @return_type
    body: (block) @func_body
  )
) @endpoint

; ============================================
; Pydantic Models
; ============================================

; class UserModel(BaseModel):
(class_definition
  name: (identifier) @model_name
  superclasses: (argument_list
    (identifier) @base_class
    (#match? @base_class "^(BaseModel|BaseSettings)$")
  )
  body: (block) @model_body
) @pydantic_model

; ============================================
; Field Definitions
; ============================================

; name: str
; email: Optional[str] = None
; items: List[Item] = Field(...)
(expression_statement
  (assignment
    left: (identifier) @field_name
    right: (_) @field_default
    type: (type) @field_type
  )
) @field_with_default

(expression_statement
  (type
    (identifier) @field_name_typed
    (type) @field_type_annotation
  )
) @field_typed

; ============================================
; Function Parameters
; ============================================

; user: UserCreate
; user: UserCreate = Body(...)
(typed_parameter
  name: (identifier) @param_name
  type: (type) @param_type
) @typed_param

(typed_default_parameter
  name: (identifier) @param_name_default
  type: (type) @param_type_default
  value: (_) @param_default_value
) @typed_param_default

; ============================================
; Enum Definitions
; ============================================

; class Status(str, Enum):
;     ACTIVE = "active"
(class_definition
  name: (identifier) @enum_name
  superclasses: (argument_list
    (identifier) @enum_base
    (#match? @enum_base "Enum")
  )
  body: (block
    (expression_statement
      (assignment
        left: (identifier) @enum_value_name
        right: (_) @enum_value
      )
    )*
  )
) @enum_class

; ============================================
; Import Statements (for dependency tracking)
; ============================================

; from fastapi import FastAPI, APIRouter
(import_from_statement
  module_name: (dotted_name) @module_name
  name: (dotted_name) @import_name
) @import_stmt

; import fastapi
(import_statement
  name: (dotted_name) @imported_module
) @simple_import
