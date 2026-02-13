; Dart tree-sitter queries for API contract extraction
; Used by FlutterExtractor for precise AST-based extraction

; ============================================
; Retrofit-style annotations
; ============================================

; @GET('/path'), @POST('/path'), etc.
(annotation
  name: (identifier) @http_method
  (#match? @http_method "^(GET|POST|PUT|PATCH|DELETE)$")
  arguments: (arguments
    (argument
      value: (string_literal) @path
    )
  )
) @retrofit_annotation

; Method following annotation
; Future<Type> methodName(params);
(method_signature
  returnType: (type_identifier) @return_type
  name: (identifier) @method_name
  formalParameters: (formal_parameter_list) @params
) @api_method

; ============================================
; Class definitions (for models)
; ============================================

; class ClassName { ... }
(class_declaration
  name: (identifier) @class_name
  body: (class_body) @class_body
) @class_def

; Field declarations
; final Type fieldName;
(declaration
  (final_builtin)?
  type: (_) @field_type
  (initialized_identifier_list
    (initialized_identifier
      name: (identifier) @field_name
    )
  )
) @field_def

; ============================================
; Enum definitions
; ============================================

; enum EnumName { value1, value2 }
(enum_declaration
  name: (identifier) @enum_name
  body: (enum_body
    (enum_constant
      name: (identifier) @enum_value
    )*
  )
) @enum_def

; ============================================
; HTTP client calls
; ============================================

; dio.get('/path'), http.post(...)
(method_invocation
  target: (identifier) @client_name
  (#match? @client_name "^(dio|_dio|http|client|httpClient)$")
  (selector
    (unconditional_assignable_selector
      (identifier) @http_method_call
      (#match? @http_method_call "^(get|post|put|patch|delete)$")
    )
  )
  arguments: (arguments
    (argument
      value: (string_literal) @api_path
    )?
  )
) @http_call

; ============================================
; Import statements (for dependency tracking)
; ============================================

; import 'package:dio/dio.dart';
(import_or_export
  (library_import
    (import_specification
      (configurable_uri
        (uri
          (string_literal) @import_path
        )
      )
    )
  )
) @import_stmt
