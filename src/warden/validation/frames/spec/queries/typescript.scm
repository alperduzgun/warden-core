; TypeScript tree-sitter queries for Angular/Vue.js API contract extraction
; Used by AngularExtractor and VueExtractor for precise AST-based extraction

; ============================================
; HTTP Client Calls (Angular HttpClient, Axios)
; ============================================

; this.http.get<User>('/api/users')
; axios.get<User[]>('/api/users')
(call_expression
  function: (member_expression
    object: (_) @client_object
    property: (property_identifier) @http_method
    (#match? @http_method "^(get|post|put|patch|delete)$")
  )
  type_arguments: (type_arguments
    (type_identifier) @response_type
  )?
  arguments: (arguments
    (string) @api_path
    (_)? @request_body
  )
) @http_call

; ============================================
; Fetch API
; ============================================

; fetch('/api/users', { method: 'POST' })
; $fetch<User>('/api/users')
(call_expression
  function: (identifier) @fetch_func
  (#match? @fetch_func "^(fetch|\\$fetch|useFetch)$")
  type_arguments: (type_arguments
    (type_identifier) @fetch_response_type
  )?
  arguments: (arguments
    (string) @fetch_path
  )
) @fetch_call

; ============================================
; Interface Definitions
; ============================================

; export interface User { ... }
(interface_declaration
  name: (type_identifier) @interface_name
  body: (interface_body
    (property_signature
      name: (property_identifier) @prop_name
      (type_annotation
        (type_identifier) @prop_type
      )
    )*
  )
) @interface_def

; ============================================
; Type Aliases
; ============================================

; export type CreateUserRequest = { ... }
(type_alias_declaration
  name: (type_identifier) @type_name
  value: (object_type
    (property_signature
      name: (property_identifier) @type_prop_name
      (type_annotation) @type_prop_type
    )*
  )
) @type_alias

; ============================================
; Enum Definitions
; ============================================

; export enum Status { Active, Inactive }
(enum_declaration
  name: (identifier) @enum_name
  body: (enum_body
    (enum_assignment
      name: (property_identifier) @enum_value
    )*
  )
) @enum_def

; ============================================
; Function/Method Definitions
; ============================================

; async function getUsers(): Promise<User[]>
; getUsers(): Observable<User[]>
(function_declaration
  name: (identifier) @func_name
  parameters: (formal_parameters) @func_params
  return_type: (type_annotation)? @func_return_type
  body: (statement_block) @func_body
) @function_def

; Arrow functions
; const getUsers = async (): Promise<User[]> => { ... }
(variable_declaration
  (variable_declarator
    name: (identifier) @arrow_func_name
    value: (arrow_function
      parameters: (formal_parameters) @arrow_params
      return_type: (type_annotation)? @arrow_return_type
      body: (_) @arrow_body
    )
  )
) @arrow_function

; ============================================
; Class Methods (Angular Services)
; ============================================

; class UserService { getUsers(): Observable<User[]> { ... } }
(method_definition
  name: (property_identifier) @method_name
  parameters: (formal_parameters) @method_params
  return_type: (type_annotation)? @method_return_type
  body: (statement_block) @method_body
) @method_def

; ============================================
; Decorators (Angular)
; ============================================

; @Injectable()
; @Component({ ... })
(decorator
  (call_expression
    function: (identifier) @decorator_name
    (#match? @decorator_name "^(Injectable|Component|Directive|Pipe|NgModule)$")
  )
) @angular_decorator

; ============================================
; Import Statements
; ============================================

; import { HttpClient } from '@angular/common/http';
; import axios from 'axios';
(import_statement
  (import_clause
    (named_imports
      (import_specifier
        name: (identifier) @import_name
      )
    )?
    (identifier)? @default_import
  )
  source: (string) @import_source
) @import_stmt
